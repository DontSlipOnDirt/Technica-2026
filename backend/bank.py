# bank.py
# The one door for money. The MCP tools (what the agent calls) and the app's endpoints
# (what the screen calls) both go through this class, so every payment is:
#   request -> fraud check on her real words -> waits for a yes -> Nessie
# A held transfer can never reach Nessie, and nothing moves money without a confirm.
# Opening an account takes the same path: "open a new safe account" is a common scam.

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import fraud_check
import gemini_signals
from models import PastTransfer, TransferRequest, TrustedContact, UserHistory
from nessie import NessieApiError


log = logging.getLogger("bank")

# Nessie's account types, keyed by how a customer says them.
ACCOUNT_TYPES = {"checking": "Checking", "savings": "Savings", "credit card": "Credit Card"}

# The payee the fraud check sees when opening an account: no money goes anywhere.
NEW_ACCOUNT = "new-account"

# Everyday words for Nessie's loan types ("home", "auto", "small business").
_LOAN_WORDS = {"car": "auto", "house": "home", "mortgage": "home"}

# The screen posts what she says while the agent is already calling a tool, so a payment
# request can arrive before the words that led to it. A line newer than WORDS_FRESH_S is
# taken to be those words; otherwise the request waits up to WORDS_WAIT_S for them.
WORDS_FRESH_S = 4.0
WORDS_WAIT_S = 2.0


class BankError(Exception):
    """Something the customer should hear about. The message is safe to read aloud."""


class PaymentUnknown(BankError):
    """Nessie may or may not have moved the money. Never say no money moved, and never retry."""


@dataclass
class DemoConfig:
    account_id: str                       # The customer's Nessie checking account
    account_name: str = "Checking"
    payees: Dict[str, str] = field(default_factory=dict)  # lowercase name -> Nessie account ID
    trusted_contact: Optional[TrustedContact] = None
    today: Optional[str] = None           # Pin the date in tests: "2026-10-17"


_TAG = re.compile(r"\s*\[[a-z]+:[^\]]*\]", re.IGNORECASE)
_PAYEE_TAG = re.compile(r"\[payee:([^\]]+)\]", re.IGNORECASE)
_MERCHANT_TAG = re.compile(r"\[merchant:([^\]]+)\]", re.IGNORECASE)


def _clean(description) -> str:
    """The seed adds tags like [merchant:...][cat:...]; the agent shouldn't read them aloud."""
    return _TAG.sub("", str(description or "")).strip()


def _payee_of(transfer: Dict[str, Any]) -> str:
    """Nessie's payee_id, or the [payee:...] tag the team's seed puts in the description."""
    if transfer.get("payee_id"):
        return transfer["payee_id"]
    match = _PAYEE_TAG.search(str(transfer.get("description", "")))
    return match.group(1) if match else ""


def _merchant_of(purchase: Dict[str, Any]) -> str:
    """Nessie's merchant_id, or the [merchant:...] tag the team's seed puts in the description."""
    if purchase.get("merchant_id"):
        return purchase["merchant_id"]
    match = _MERCHANT_TAG.search(str(purchase.get("description", "")))
    return match.group(1) if match else ""


def _as_datetime(date: str) -> str:
    """Nessie dates are "2026-10-17"; the fraud check wants "2026-10-17T00:00:00"."""
    return date if "T" in date else f"{date}T00:00:00"


def _plain(name, noun: str = "account") -> str:
    """'my Savings account' -> 'savings', so names match however the agent phrases them."""
    words = str(name or "").lower().split()
    if words[:1] in (["my"], ["the"]):
        words = words[1:]
    if words[-1:] == [noun]:
        words = words[:-1]
    return " ".join(words)


def account_phrase(name: str) -> str:
    """How an account sounds in a sentence: 'your checking account', but 'your Rainy day account'."""
    return name.lower() if name.lower() in ACCOUNT_TYPES else name


def _number(value) -> Optional[float]:
    """A Nessie amount as a float, or None when it's missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _is_due(bill: Dict[str, Any]) -> bool:
    return bill.get("status") not in ("completed", "cancelled")


def _is_recurring(bill: Dict[str, Any]) -> bool:
    """Nessie marks a repeating bill with a recurring_date or the status "recurring"."""
    return bool(bill.get("recurring_date")) or bill.get("status") == "recurring"


def _loan_name(loan: Dict[str, Any]) -> str:
    """'Auto loan', from Nessie's loan type."""
    kind = str(loan.get("type") or "").strip()
    return f"{kind.capitalize()} loan" if kind else "Loan"


def _category(merchant: Dict[str, Any]) -> str:
    category = merchant.get("category") or ""
    return ", ".join(map(str, category)) if isinstance(category, list) else str(category)


def _address(merchant: Dict[str, Any]) -> str:
    """'7 Knox Rd, College Park, MD 20740' from Nessie's address fields."""
    a = merchant.get("address") or {}
    street = " ".join(str(a[k]) for k in ("street_number", "street_name") if a.get(k))
    region = " ".join(str(a[k]) for k in ("state", "zip") if a.get(k))
    return ", ".join(part for part in (street, str(a.get("city") or ""), region) if part)


class Bank:
    def __init__(self, nessie, config: DemoConfig):
        self._nessie = nessie
        self._config = config
        self._lock = threading.Lock()
        self._words_arrived = threading.Condition(self._lock)
        self._conversation_id: Optional[str] = None
        self._lines: List[str] = []
        self._last_line_at: Optional[float] = None   # time.monotonic() of the newest line
        self._transfers: Dict[str, Dict[str, Any]] = {}
        self._private: Dict[str, Dict[str, Any]] = {}   # transfer_id -> what Nessie needs to send it
        self._current_id: Optional[str] = None
        self._held_payees: set = set()
        self._customer_id: Optional[str] = None
        self._opened: set = set()   # Accounts opened through this server: not trusted payees yet

    # ---- Transcript ------------------------------------------------------------

    def add_transcript_line(self, conversation_id: str, text: str) -> None:
        """The app forwards every finished user line. A new conversation starts a fresh transcript."""
        with self._words_arrived:
            if conversation_id != self._conversation_id:
                self._conversation_id = conversation_id
                self._lines = []
            self._lines.append(text)
            self._last_line_at = time.monotonic()
            self._words_arrived.notify_all()
            said = " ".join(self._lines)
        # Check what they've said so far while they keep talking; request_transfer reuses it.
        gemini_signals.prefetch(said)

    def _wait_for_words(self) -> None:
        """Give the screen a moment to send the words behind this request. Only when a screen
        is sending lines at all; without one (testing the agent alone) there's nothing to wait for."""
        with self._words_arrived:
            seen = self._last_line_at
            if seen is None or time.monotonic() - seen < WORDS_FRESH_S:
                return
            self._words_arrived.wait_for(lambda: self._last_line_at != seen, timeout=WORDS_WAIT_S)

    # ---- Requests (from the agent) ----------------------------------------------

    def request_transfer(self, payee_name: str, amount: float, memo: str = "") -> Dict[str, Any]:
        payee_id = self._config.payees.get(payee_name.strip().lower())
        if not payee_id:
            raise BankError(f"I don't have {payee_name} as someone you can send money to.")
        return self._start("transfer", self._config.account_id, payee_name.strip(), payee_id, amount, memo)

    def transfer_between_accounts(self, from_account: str, to_account: str, amount: float,
                                  memo: str = "") -> Dict[str, Any]:
        """Move money between two of her own accounts, named the way she says them."""
        accounts = self._accounts()
        source = self._find_account(from_account, accounts)
        destination = self._find_account(to_account, accounts)
        if source.get("_id") == destination.get("_id"):
            raise BankError("Those are the same account. Please pick two different accounts.")
        return self._start("own_transfer", source["_id"], self._name_of(destination), destination["_id"],
                           amount, memo, accounts)

    def pay_bill(self, biller_name: str, amount: Optional[float] = None, from_account: str = "") -> Dict[str, Any]:
        accounts = self._accounts()
        bill = self._find_bill(biller_name, accounts)
        if not bill:
            raise BankError(f"I couldn't find a bill from {biller_name}.")
        payee = bill.get("payee", biller_name)
        owed = _number(bill.get("payment_amount"))
        if amount is None:
            if owed is None:
                raise BankError(f"How much would you like to pay {payee}?")
            amount = owed
        elif owed is not None and amount > owed:
            raise BankError(f"That's more than the ${owed:,.2f} you owe {payee}.")
        source = self._source(from_account, accounts)
        return self._start("bill", source["_id"], payee, f"biller:{payee.lower()}", amount, "", accounts,
                           bill_id=bill.get("_id"), owed=owed)

    def pay_loan(self, loan_name: str = "", amount: Optional[float] = None,
                 from_account: str = "") -> Dict[str, Any]:
        accounts = self._accounts()
        loan = self._find_loan(loan_name, accounts)
        name = _loan_name(loan)
        owed = _number(loan.get("amount"))
        if owed is not None and owed <= 0:
            raise BankError(f"Your {name.lower()} is already paid off.")
        if amount is None:
            monthly = _number(loan.get("monthly_payment"))
            if monthly is None:
                raise BankError(f"How much would you like to pay on your {name.lower()}?")
            amount = monthly if owed is None else min(monthly, owed)
        elif owed is not None and amount > owed:
            raise BankError(f"That's more than the ${owed:,.2f} still owed on your {name.lower()}.")
        source = self._source(from_account, accounts)
        return self._start("loan", source["_id"], name, f"loan:{loan.get('_id')}", amount, "", accounts,
                           loan_id=loan.get("_id"), owed=owed)

    def withdraw(self, amount: float, memo: str = "") -> Dict[str, Any]:
        # Cash out is a common end to a scam, so it gets the same fraud check as a transfer.
        return self._start("withdrawal", self._config.account_id, "cash", "cash:withdrawal", amount,
                           memo or "Withdrawal")

    def deposit(self, amount: float, memo: str = "") -> Dict[str, Any]:
        return self._start("deposit", self._config.account_id, "deposit", "cash:deposit", amount, memo or "Deposit")

    def create_account(self, account_type: str, nickname: str = "") -> Dict[str, Any]:
        """Open an account with $0 in it. It still gets the fraud check and needs a yes:
        "open a new safe account and move your money into it" is a common scam."""
        type_name = ACCOUNT_TYPES.get(_plain(account_type))
        if not type_name:
            raise BankError("I can open a checking, savings, or credit card account.")
        accounts = self._accounts()
        if not self._customer_id:
            raise BankError("I can't open an account right now.")
        return self._start("new_account", self._config.account_id, nickname.strip() or type_name, NEW_ACCOUNT,
                           0.0, "", accounts, account_type=type_name, customer_id=self._customer_id)

    def _start(self, kind: str, source_id: str, payee_name: str, payee_id: str, amount: float, memo: str,
               accounts: Optional[List[Dict[str, Any]]] = None, **details: Any) -> Dict[str, Any]:
        """Fraud-check a request and park it until she says yes. details: what confirm needs later."""
        if not math.isfinite(amount) or round(amount, 2) != amount:
            raise BankError("Please give the amount in dollars and cents.")
        if amount <= 0 and kind != "new_account":
            raise BankError("The amount has to be more than zero.")
        accounts = self._accounts() if accounts is None else accounts
        source = self._by_id(source_id, accounts)
        history = self._history(source, accounts, payee_id)
        self._wait_for_words()
        with self._lock:
            request = TransferRequest(
                from_account_id=source_id,
                to_account_id=payee_id,
                amount=amount,
                user_said=" ".join(self._lines),
                description=memo,
                requested_at=self._now(),
            )
            decision = fraud_check.check_transfer(request, history)

            # Once a payee has been held, every later request to them is held too.
            already_held = payee_id in self._held_payees
            # Nothing about opening an account is urgent, so any warning sign stops it.
            held = (decision.decision == "hold" or already_held
                    or (kind == "new_account" and decision.decision == "confirm"))
            if held:
                self._held_payees.add(payee_id)

            # A new request replaces anything still waiting for a yes.
            for t in self._transfers.values():
                if t["status"] == "awaiting_yes":
                    t["status"] = "cancelled"

            reasons = list(decision.reasons)
            if already_held and decision.decision != "hold":
                reasons.append("Opening an account was already stopped" if kind == "new_account"
                               else "A payment to this person was already stopped")
            transfer = {
                "transfer_id": decision.transfer_id,
                "kind": kind,
                "status": "held" if held else "awaiting_yes",
                "decision": "hold" if held else decision.decision,
                "risk_score": decision.risk_score,
                "reasons": reasons,
                "payee_name": payee_name,
                "amount": amount,
                "from_account_name": self._name_of(source),
            }
            if kind == "new_account":
                transfer["account_type"] = details["account_type"]
            if kind in ("bill", "loan"):
                transfer["amount_owed"] = details["owed"]
            transfer["spoken_message"] = self._spoken(transfer, careful=decision.decision == "confirm")
            self._transfers[transfer["transfer_id"]] = transfer
            # The request and history are kept so the yes can be checked again against anything said since.
            self._private[transfer["transfer_id"]] = {"source_id": source_id, "payee_id": payee_id, "memo": memo,
                                                      "request": request, "history": history, **details}
            self._current_id = transfer["transfer_id"]
            return dict(transfer)

    def _spoken(self, t: Dict[str, Any], careful: bool) -> str:
        why = "".join(f" {r}." for r in t["reasons"])
        if t["status"] == "held":
            # Our own wording: the fraud check's message offers a PIN release, which this app doesn't have.
            if t["kind"] == "new_account":
                return (
                    f"I haven't opened this account, to keep your money safe.{why} "
                    "Capital One will never ask you to open an account or move money to keep it safe. "
                    "If you think this is a mistake, please call Capital One."
                )
            return (
                f"I've stopped this payment to keep your money safe.{why} "
                "Capital One will never ask you to move money to keep it safe. "
                "If you think this is a mistake, please call Capital One."
            )
        ask = self._ask(t)
        if careful:
            # A "confirm" decision: say why before asking, so the yes is an informed one.
            return f"Before I do this, please double-check.{why} {ask}"
        return ask

    @staticmethod
    def _ask(t: Dict[str, Any]) -> str:
        money, payee, kind = f"${t['amount']:,.2f}", t["payee_name"], t["kind"]
        account = account_phrase(t["from_account_name"])
        if kind == "withdrawal":
            return f"I'll take {money} out of your {account} account. Are you sure?"
        if kind == "deposit":
            return f"I'll put {money} into your {account} account. Are you sure?"
        if kind == "own_transfer":
            return f"I'll move {money} from your {account} account to your {account_phrase(payee)} account. Are you sure?"
        if kind == "loan":
            return f"I'll pay {money} toward your {payee.lower()} from your {account} account. Are you sure?"
        if kind == "bill" and t["amount_owed"] is not None and t["amount"] < t["amount_owed"]:
            return (f"I'll pay {money} of your ${t['amount_owed']:,.2f} {payee} bill from your {account} account. "
                    "The rest stays due. Are you sure?")
        if kind == "new_account":
            called = "" if payee == t["account_type"] else f" called {payee}"
            return f"I'll open a new {t['account_type'].lower()} account{called}, with a $0.00 balance. Are you sure?"
        return f"I'll pay {payee} {money} from your {account} account. Are you sure?"

    # ---- Yes / No (from the agent or the app) ------------------------------------

    def confirm(self, transfer_id: str) -> Dict[str, Any]:
        with self._lock:
            t = self._transfers.get(transfer_id)
            if not t:
                raise BankError("I couldn't find that payment.")
            if t["status"] == "executed":
                return dict(t)   # Already sent; never send twice.
            if t["status"] == "unknown":
                raise PaymentUnknown(self._unsure(t))   # It may have gone through; never risk sending twice.
            if t["status"] != "awaiting_yes" or not fraud_check.is_cleared_to_send(transfer_id):
                raise BankError("That payment can't be sent.")
            p = self._private[transfer_id]
            if self._held_on_second_look(t, p):
                raise BankError(t["spoken_message"])
            try:
                self._send(t, p)
            except PaymentUnknown:
                t["status"] = "unknown"
                raise
            except NessieApiError as err:
                log.warning("Nessie payment for %s failed with status %s: %s", transfer_id, err.status, err.detail)
                if err.outcome_unknown:
                    t["status"] = "unknown"
                    raise PaymentUnknown(self._unsure(t))
                raise BankError("I couldn't open that account." if t["kind"] == "new_account"
                                else "I couldn't complete that payment.")
            t["status"] = "executed"
            return dict(t)

    def _held_on_second_look(self, t: Dict[str, Any], p: Dict[str, Any]) -> bool:
        """Check the request again if she has said more since it was checked, or her words reached
        us late. A hold now stops it before any money moves. Call with the lock held."""
        said = " ".join(self._lines)
        if said == p["request"].user_said:
            return False
        decision = fraud_check.check_transfer(replace(p["request"], user_said=said), p["history"])
        if not (decision.decision == "hold" or (t["kind"] == "new_account" and decision.decision == "confirm")):
            return False
        self._held_payees.add(p["payee_id"])
        t.update(status="held", decision="hold", risk_score=decision.risk_score, reasons=list(decision.reasons))
        t["spoken_message"] = self._spoken(t, careful=False)
        return True

    @staticmethod
    def _unsure(t: Dict[str, Any]) -> str:
        if t["kind"] == "new_account":
            return "I'm not sure the account was opened. Please check your accounts before trying again."
        return ("I'm not sure that payment went through. Please don't try it again yet. "
                "Check your balance first, or call Capital One.")

    def _send(self, t: Dict[str, Any], p: Dict[str, Any]) -> None:
        """The Nessie calls for a request that got its yes. The first call moves the money, so if it
        fails nothing has moved. The calls after it only keep Nessie's records straight."""
        kind, source, amount = t["kind"], p["source_id"], t["amount"]

        def cash(description: str) -> Dict[str, Any]:
            # Nessie's DepositCreate (and WithdrawalCreate) refuse a request without a status.
            return {"medium": "balance", "status": "completed", "amount": amount, "transaction_date": self._today(),
                    "description": description}

        if kind in ("withdrawal", "deposit"):
            self._nessie.post(f"/accounts/{source}/{kind}s", cash(p["memo"]))
        elif kind in ("transfer", "own_transfer"):
            # Nessie's TransferCreate has no payee field; like the team's seed, the
            # payee rides in the description as a [payee:...] tag that _payee_of reads.
            memo = p["memo"] or f"Transfer to {t['payee_name']}"
            self._nessie.post(f"/accounts/{source}/transfers", {
                "transaction_date": self._today(),
                "status": "completed",
                "amount": amount,
                "description": f"{memo} [payee:{p['payee_id']}]",
            })
            if kind == "own_transfer":
                # With no payee field the transfer can't credit her other account, so a deposit does.
                try:
                    self._nessie.post(f"/accounts/{p['payee_id']}/deposits", cash(f"Transfer from {t['from_account_name']}"))
                except NessieApiError as err:
                    log.warning("Nessie deposit for %s failed after the money left, status %s: %s",
                                t["transfer_id"], err.status, err.detail)
                    raise PaymentUnknown(
                        f"The money left your {account_phrase(t['from_account_name'])} account, but I couldn't "
                        f"confirm it reached your {account_phrase(t['payee_name'])} account. Please don't try it "
                        "again; call Capital One so they can check it.")
        elif kind == "bill":
            self._nessie.post(f"/accounts/{source}/withdrawals", cash(f"Bill payment: {t['payee_name']}"))
            left = None if p["owed"] is None else round(p["owed"] - amount, 2)
            # Paid in full, the bill is done; paid in part, it stays due for the rest.
            self._follow_up("put", f"/bills/{p['bill_id']}",
                            {"payment_amount": left} if left else {"status": "completed"})
        elif kind == "loan":
            # Like the Nessie-framework handler: take the money out, then lower what's owed.
            self._nessie.post(f"/accounts/{source}/withdrawals", cash(f"Loan payment: {t['payee_name']}"))
            if p["owed"] is not None:
                self._follow_up("put", f"/loans/{p['loan_id']}", {"amount": round(p["owed"] - amount, 2)})
        elif kind == "new_account":
            created = self._nessie.post(f"/customers/{p['customer_id']}/accounts", {
                "type": t["account_type"], "nickname": t["payee_name"], "rewards": 0, "balance": 0,
            })
            new = created.get("objectCreated") if isinstance(created, dict) else None
            if isinstance(new, dict) and new.get("_id"):
                self._opened.add(new["_id"])

    def _follow_up(self, method: str, path: str, body: Dict[str, Any]) -> None:
        """A Nessie call after the money has moved: log a failure, never undo or repeat the payment."""
        try:
            getattr(self._nessie, method)(path, body)
        except NessieApiError as err:
            log.warning("Nessie %s %s after a payment failed with status %s: %s",
                        method.upper(), path, err.status, err.detail)

    def cancel(self, transfer_id: str) -> Dict[str, Any]:
        with self._lock:
            t = self._transfers.get(transfer_id)
            if not t:
                raise BankError("I couldn't find that payment.")
            if t["status"] == "executed":
                raise BankError("That payment was already sent.")
            if t["status"] == "unknown":
                raise PaymentUnknown(self._unsure(t))
            if t["status"] == "awaiting_yes":
                t["status"] = "cancelled"
            return dict(t)

    def current(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._transfers[self._current_id]) if self._current_id else None

    # ---- Read-only answers -------------------------------------------------------
    # Accounts, bills and loans go out by name. Nessie IDs stay on the server.

    def summary(self) -> Dict[str, Any]:
        account = self._get(f"/accounts/{self._config.account_id}") or {}
        return {
            "balance": account.get("balance"),
            "account_name": self._config.account_name,
            "bills_due": [{k: b[k] for k in ("biller_name", "amount", "due_date")} for b in self.bills()],
        }

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Every account the customer has, by name."""
        return [{"name": self._name_of(a), "type": a.get("type"), "balance": a.get("balance")}
                for a in self._accounts()]

    def recent_purchases(self, limit: int = 10, merchant_name: str = "", account_name: str = "") -> List[Dict[str, Any]]:
        rows = self._each("purchases", self._pick(account_name))
        rows.sort(key=lambda row: row[1].get("purchase_date") or "", reverse=True)
        wanted = merchant_name.strip().lower()
        if wanted:
            merchants = self._merchants([p for _, p in rows])
            rows = [(a, p) for a, p in rows
                    if wanted in _clean(p.get("description")).lower()
                    or wanted in str(merchants.get(_merchant_of(p), {}).get("name", "")).lower()]
        return [
            {"description": _clean(p.get("description")), "amount": p.get("amount"),
             "date": p.get("purchase_date"), "account": self._name_of(a)}
            for a, p in rows[:max(limit, 1)]
        ]

    def deposits(self, account_name: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        return self._cash_history("deposits", account_name, limit)

    def withdrawals(self, account_name: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        return self._cash_history("withdrawals", account_name, limit)

    def _cash_history(self, what: str, account_name: str, limit: int) -> List[Dict[str, Any]]:
        rows = self._each(what, self._pick(account_name))
        rows.sort(key=lambda row: row[1].get("transaction_date") or "", reverse=True)
        return [
            {"account": self._name_of(a), "description": _clean(r.get("description")), "amount": r.get("amount"),
             "date": r.get("transaction_date"), "status": r.get("status")}
            for a, r in rows[:max(limit, 1)]
        ]

    def transfers(self, account_name: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        """Transfers newest first. 'from' and 'to' are names: her accounts or her payees."""
        accounts = self._accounts()
        names = {payee_id: name.title() for name, payee_id in self._config.payees.items()}
        names.update({a.get("_id"): self._name_of(a) for a in accounts})
        rows, seen = [], set()
        for account, t in self._each("transfers", self._pick(account_name, accounts)):
            if t.get("_id") in seen:
                continue   # A move between her accounts can show up under both.
            if t.get("_id"):
                seen.add(t["_id"])
            rows.append({
                "from": names.get(t.get("payer_id") or account.get("_id")),
                "to": names.get(_payee_of(t)),
                "amount": t.get("amount"),
                "date": t.get("transaction_date"),
                "description": _clean(t.get("description")),
                "status": t.get("status"),
            })
        rows.sort(key=lambda r: r["date"] or "", reverse=True)
        return rows[:max(limit, 1)]

    def bills(self, account_name: str = "", recurring: Optional[bool] = None,
              include_paid: bool = False) -> List[Dict[str, Any]]:
        """Bills still due, soonest first. include_paid adds paid and cancelled ones;
        recurring=True keeps only repeating bills, False only one-time bills."""
        rows = []
        for account, b in self._each("bills", self._pick(account_name)):
            if (include_paid or _is_due(b)) and (recurring is None or _is_recurring(b) == recurring):
                rows.append({
                    "biller_name": b.get("payee"),
                    "amount": b.get("payment_amount"),
                    "due_date": b.get("payment_date") or b.get("upcoming_payment_date"),
                    "status": b.get("status"),
                    "recurring": _is_recurring(b),
                    "account": self._name_of(account),
                })
        rows.sort(key=lambda r: r["due_date"] or "")
        return rows

    def loans(self) -> List[Dict[str, Any]]:
        return [
            {"name": _loan_name(loan), "amount_owed": loan.get("amount"),
             "monthly_payment": loan.get("monthly_payment"), "status": loan.get("status"),
             "description": _clean(loan.get("description")), "account": self._name_of(a)}
            for a, loan in self._each("loans", self._accounts())
        ]

    def find_merchant(self, name: str) -> List[Dict[str, Any]]:
        """Stores she has bought from whose name matches, at most 5. Nessie's full merchant
        list is huge and mostly other people's, so this only looks at her own purchases."""
        wanted = name.strip().lower()
        if not wanted:
            raise BankError("Which store do you mean?")
        purchases = [p for _, p in self._each("purchases", self._accounts())]
        found = [m for m in self._merchants(purchases).values() if wanted in str(m.get("name", "")).lower()]
        return [{"name": m.get("name"), "category": _category(m), "address": _address(m)} for m in found[:5]]

    # ---- Helpers -----------------------------------------------------------------

    def _get(self, path: str) -> Any:
        try:
            return self._nessie.get(path)
        except NessieApiError as err:
            # Path and status only; the API key never reaches the logs.
            log.warning("Nessie GET %s failed with status %s: %s", path, err.status, err.detail)
            raise BankError("I couldn't reach the bank right now.")

    def _accounts(self) -> List[Dict[str, Any]]:
        """All of her accounts, Nessie IDs included."""
        if not self._customer_id:
            main = self._get(f"/accounts/{self._config.account_id}") or {}
            self._customer_id = main.get("customer_id")
            if not self._customer_id:
                return [main] if main else []
        return self._get(f"/customers/{self._customer_id}/accounts") or []

    def _pick(self, account_name: str, accounts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """The one account she named, or all of them."""
        accounts = self._accounts() if accounts is None else accounts
        return [self._find_account(account_name, accounts)] if str(account_name or "").strip() else accounts

    def _each(self, what: str, accounts: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Every record of one kind ("bills", "loans", ...) across these accounts, with its account."""
        return [(a, record) for a in accounts for record in (self._get(f"/accounts/{a.get('_id')}/{what}") or [])]

    def _by_id(self, account_id: str, accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
        for a in accounts:
            if a.get("_id") == account_id:
                return a
        return self._get(f"/accounts/{account_id}") or {"_id": account_id}

    def _name_of(self, account: Dict[str, Any]) -> str:
        if account.get("_id") == self._config.account_id:
            return self._config.account_name
        return account.get("nickname") or account.get("type") or "account"

    def _source(self, from_account: str, accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Payments come from checking unless she names another account."""
        if str(from_account or "").strip():
            return self._find_account(from_account, accounts)
        return self._by_id(self._config.account_id, accounts)

    def _find_account(self, name: str, accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Her account by nickname or type: 'savings', 'my credit card', 'Rainy day'."""
        wanted = _plain(name)
        if not wanted:
            raise BankError("Which account do you mean?")

        def names(a: Dict[str, Any]) -> set:
            return {_plain(a.get("nickname")), _plain(self._name_of(a))}

        matches = ([a for a in accounts if wanted in names(a)]
                   or [a for a in accounts if wanted == _plain(a.get("type"))]
                   or [a for a in accounts if any(wanted in n for n in names(a) | {_plain(a.get("type"))})])
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise BankError(f"I couldn't find an account called {name}.")
        options = " or ".join(self._name_of(a) for a in matches)
        raise BankError(f"You have more than one account that could be {name}: {options}. Which one do you mean?")

    def _find_bill(self, biller_name: str, accounts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        wanted = biller_name.strip().lower()
        for _, bill in self._each("bills", accounts):
            if _is_due(bill) and wanted in str(bill.get("payee", "")).lower():
                return bill
        return None

    def _find_loan(self, loan_name: str, accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Her loan by type or description: 'auto', 'my car loan', 'Honda'. Blank works if she has one."""
        loans = [loan for _, loan in self._each("loans", accounts)]
        if not loans:
            raise BankError("I don't see any loans on your accounts.")
        wanted = _plain(loan_name, "loan")
        wanted = _LOAN_WORDS.get(wanted, wanted)
        matches = [loan for loan in loans
                   if wanted in _plain(_loan_name(loan), "loan")
                   or wanted in _clean(loan.get("description")).lower()] if wanted else loans
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise BankError(f"I couldn't find a loan called {loan_name}.")
        options = " or ".join(_loan_name(loan) for loan in matches)
        raise BankError(f"You have more than one loan: {options}. Which one do you mean?")

    def _merchants(self, purchases: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Details for the merchants on these purchases, one Nessie call each. A merchant
        Nessie can't find is skipped rather than failing the whole answer."""
        found = {}
        for merchant_id in sorted({_merchant_of(p) for p in purchases} - {""}):
            try:
                merchant = self._nessie.get(f"/merchants/{merchant_id}")
            except NessieApiError as err:
                log.warning("Nessie GET /merchants/%s failed with status %s: %s", merchant_id, err.status, err.detail)
                continue
            if isinstance(merchant, dict):
                found[merchant_id] = merchant
        return found

    def _history(self, source: Dict[str, Any], accounts: List[Dict[str, Any]], payee_id: str) -> UserHistory:
        source_id = source.get("_id")
        # Only transfers she sent where we can tell who got the money. That also skips
        # test transfers someone left in Nessie, which would drag her "usual amount" down.
        transfers = [t for t in (self._get(f"/accounts/{source_id}/transfers") or [])
                     if t.get("payer_id", source_id) == source_id
                     and t.get("status") != "cancelled" and _payee_of(t)]
        own = {a.get("_id") for a in accounts}
        known = [_payee_of(t) for t in transfers]
        # Her own accounts aren't new payees, except ones opened through this server:
        # "open a new account and move your money into it" is a common scam.
        known += [account_id for account_id in own if account_id not in self._opened]
        # Bills and loans only matter when paying one, so skip those lookups otherwise.
        if payee_id.startswith("biller:"):
            known += [f"biller:{str(b.get('payee', '')).lower()}" for _, b in self._each("bills", accounts)]
        if payee_id.startswith("loan:"):
            known += [f"loan:{loan.get('_id')}" for _, loan in self._each("loans", accounts)]
        known.append(NEW_ACCOUNT)   # Opening an account sends money nowhere.
        # Her usual amount is what she sends to people; moving her own money around doesn't count.
        amounts = [float(t.get("amount", 0)) for t in transfers if _payee_of(t) not in own]
        return UserHistory(
            known_payees=known,
            average_transfer=sum(amounts) / len(amounts) if amounts else 0.0,
            current_balance=float(source.get("balance") or 0),
            recent_transfers=[
                PastTransfer(to_account_id=_payee_of(t), amount=float(t.get("amount", 0)),
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
