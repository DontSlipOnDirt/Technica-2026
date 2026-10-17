# bank.py
# The one door for money. The MCP tools (what the agent calls) and the app's endpoints
# (what the screen calls) both go through this class, so every payment is:
#   request -> fraud check on her real words -> waits for a yes -> Nessie
# A held transfer can never reach Nessie, and nothing moves money without a confirm.

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import fraud_check
from models import PastTransfer, TransferRequest, TrustedContact, UserHistory
from nessie import NessieApiError


class BankError(Exception):
    """Something the customer should hear about. The message is safe to read aloud."""


@dataclass
class DemoConfig:
    account_id: str                       # The customer's Nessie checking account
    account_name: str = "Checking"
    payees: Dict[str, str] = field(default_factory=dict)  # lowercase name -> Nessie account ID
    trusted_contact: Optional[TrustedContact] = None
    today: Optional[str] = None           # Pin the date in tests: "2026-10-17"


def _as_datetime(date: str) -> str:
    """Nessie dates are "2026-10-17"; the fraud check wants "2026-10-17T00:00:00"."""
    return date if "T" in date else f"{date}T00:00:00"


class Bank:
    def __init__(self, nessie, config: DemoConfig):
        self._nessie = nessie
        self._config = config
        self._lock = threading.Lock()
        self._conversation_id: Optional[str] = None
        self._lines: List[str] = []
        self._transfers: Dict[str, Dict[str, Any]] = {}
        self._private: Dict[str, Dict[str, Any]] = {}   # transfer_id -> what Nessie needs to send it
        self._current_id: Optional[str] = None
        self._held_payees: set = set()

    # ---- Transcript ------------------------------------------------------------

    def add_transcript_line(self, conversation_id: str, text: str) -> None:
        """The app forwards every finished user line. A new conversation starts a fresh transcript."""
        with self._lock:
            if conversation_id != self._conversation_id:
                self._conversation_id = conversation_id
                self._lines = []
            self._lines.append(text)

    # ---- Requests (from the agent) ----------------------------------------------

    def request_transfer(self, payee_name: str, amount: float, memo: str = "") -> Dict[str, Any]:
        payee_id = self._config.payees.get(payee_name.strip().lower())
        if not payee_id:
            raise BankError(f"I don't have {payee_name} as someone you can send money to.")
        return self._start("transfer", payee_name.strip(), payee_id, amount, memo, bill_id=None)

    def pay_bill(self, biller_name: str, amount: Optional[float] = None) -> Dict[str, Any]:
        bill = self._find_bill(biller_name)
        if not bill:
            raise BankError(f"I couldn't find a bill from {biller_name}.")
        pay = amount if amount is not None else float(bill.get("payment_amount", 0))
        payee = bill.get("payee", biller_name)
        return self._start("bill", payee, f"biller:{payee.lower()}", pay, "", bill_id=bill.get("_id"))

    def _start(self, kind: str, payee_name: str, payee_id: str, amount: float, memo: str,
               bill_id: Optional[str]) -> Dict[str, Any]:
        if amount <= 0:
            raise BankError("The amount has to be more than zero.")
        history = self._history()
        with self._lock:
            request = TransferRequest(
                from_account_id=self._config.account_id,
                to_account_id=payee_id,
                amount=amount,
                user_said=" ".join(self._lines),
                description=memo,
                requested_at=self._now(),
            )
            decision = fraud_check.check_transfer(request, history)

            # Once a payee has been held, every later request to them is held too.
            held = decision.decision == "hold" or payee_id in self._held_payees
            if held:
                self._held_payees.add(payee_id)

            # A new request replaces anything still waiting for a yes.
            for t in self._transfers.values():
                if t["status"] == "awaiting_yes":
                    t["status"] = "cancelled"

            reasons = list(decision.reasons)
            if held and decision.decision != "hold":
                reasons.append("A payment to this person was already stopped")
            transfer = {
                "transfer_id": decision.transfer_id,
                "kind": kind,
                "status": "held" if held else "awaiting_yes",
                "decision": "hold" if held else decision.decision,
                "risk_score": decision.risk_score,
                "reasons": reasons,
                "spoken_message": self._spoken(held, reasons, payee_name, amount),
                "payee_name": payee_name,
                "amount": amount,
                "from_account_name": self._config.account_name,
            }
            self._transfers[transfer["transfer_id"]] = transfer
            self._private[transfer["transfer_id"]] = {"payee_id": payee_id, "memo": memo, "bill_id": bill_id}
            self._current_id = transfer["transfer_id"]
            return dict(transfer)

    def _spoken(self, held: bool, reasons: List[str], payee_name: str, amount: float) -> str:
        if held:
            # Our own wording: the fraud check's message offers a PIN release, which this app doesn't have.
            why = "".join(f" {r}." for r in reasons)
            return (
                f"I've stopped this payment to keep your money safe.{why} "
                "Capital One will never ask you to move money to keep it safe. "
                "If you think this is a mistake, please call Capital One."
            )
        return f"I'll pay {payee_name} ${amount:,.2f} from your {self._config.account_name.lower()} account. Are you sure?"

    # ---- Yes / No (from the agent or the app) ------------------------------------

    def confirm(self, transfer_id: str) -> Dict[str, Any]:
        with self._lock:
            t = self._transfers.get(transfer_id)
            if not t:
                raise BankError("I couldn't find that payment.")
            if t["status"] == "executed":
                return dict(t)   # Already sent; never send twice.
            if t["status"] != "awaiting_yes" or not fraud_check.is_cleared_to_send(transfer_id):
                raise BankError("That payment can't be sent.")
            private = self._private[transfer_id]
            try:
                if t["kind"] == "bill":
                    self._nessie.put(f"/bills/{private['bill_id']}", {"status": "completed"})
                else:
                    body = {
                        "medium": "balance",
                        "payee_id": private["payee_id"],
                        "amount": t["amount"],
                        "transaction_date": self._today(),
                    }
                    if private["memo"]:
                        body["description"] = private["memo"]
                    self._nessie.post(f"/accounts/{self._config.account_id}/transfers", body)
            except NessieApiError:
                raise BankError("I couldn't complete that payment.")
            t["status"] = "executed"
            return dict(t)

    def cancel(self, transfer_id: str) -> Dict[str, Any]:
        with self._lock:
            t = self._transfers.get(transfer_id)
            if not t:
                raise BankError("I couldn't find that payment.")
            if t["status"] == "executed":
                raise BankError("That payment was already sent.")
            if t["status"] == "awaiting_yes":
                t["status"] = "cancelled"
            return dict(t)

    def current(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._transfers[self._current_id]) if self._current_id else None

    # ---- Read-only answers -------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        account = self._get(f"/accounts/{self._config.account_id}") or {}
        bills = self._get(f"/accounts/{self._config.account_id}/bills") or []
        return {
            "balance": account.get("balance"),
            "account_name": self._config.account_name,
            "bills_due": [
                {"biller_name": b.get("payee"), "amount": b.get("payment_amount"), "due_date": b.get("payment_date")}
                for b in bills if b.get("status") != "completed"
            ],
        }

    def recent_purchases(self, limit: int = 10) -> List[Dict[str, Any]]:
        purchases = self._get(f"/accounts/{self._config.account_id}/purchases") or []
        purchases = sorted(purchases, key=lambda p: p.get("purchase_date", ""), reverse=True)
        return [
            {"description": p.get("description"), "amount": p.get("amount"), "date": p.get("purchase_date")}
            for p in purchases[:limit]
        ]

    # ---- Helpers -----------------------------------------------------------------

    def _get(self, path: str) -> Any:
        try:
            return self._nessie.get(path)
        except NessieApiError:
            raise BankError("I couldn't reach the bank right now.")

    def _find_bill(self, biller_name: str) -> Optional[Dict[str, Any]]:
        wanted = biller_name.strip().lower()
        bills = self._get(f"/accounts/{self._config.account_id}/bills") or []
        for bill in bills:
            if bill.get("status") != "completed" and wanted in str(bill.get("payee", "")).lower():
                return bill
        return None

    def _history(self) -> UserHistory:
        account_id = self._config.account_id
        account = self._get(f"/accounts/{account_id}") or {}
        transfers = [t for t in (self._get(f"/accounts/{account_id}/transfers") or [])
                     if t.get("payer_id", account_id) == account_id]
        bills = self._get(f"/accounts/{account_id}/bills") or []
        amounts = [float(t.get("amount", 0)) for t in transfers]
        return UserHistory(
            known_payees=[t.get("payee_id") for t in transfers] +
                         [f"biller:{str(b.get('payee', '')).lower()}" for b in bills],
            average_transfer=sum(amounts) / len(amounts) if amounts else 0.0,
            current_balance=float(account.get("balance", 0)),
            recent_transfers=[
                PastTransfer(to_account_id=t.get("payee_id", ""), amount=float(t.get("amount", 0)),
                             made_at=_as_datetime(t.get("transaction_date", self._today())))
                for t in transfers[-20:]
            ],
            trusted_contact=self._config.trusted_contact,
        )

    def _today(self) -> str:
        return self._config.today or datetime.now().strftime("%Y-%m-%d")

    def _now(self) -> str:
        if self._config.today:
            return f"{self._config.today}T12:00:00"
        return datetime.now().isoformat(timespec="seconds")
