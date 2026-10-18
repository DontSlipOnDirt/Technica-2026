# app.py
# One web app with two doors into the same Bank:
#   /mcp      - the MCP server the ElevenLabs agent connects to (streamable HTTP)
#   /api/...  - the endpoints the voice screen calls (transcript, current transfer, Yes/No)
# Replaces Jacob's stdio TypeScript server: ElevenLabs can only reach MCP servers over HTTP.

import json
import os
from datetime import datetime
from typing import Any, Callable, List, Optional, Tuple

import anyio
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from bank import Bank, BankError, PaymentUnknown, account_phrase

NO_MONEY_MOVED = "No money was moved."

INSTRUCTIONS = (
    "Banking tools for a Capital One voice assistant. Every tool replies with JSON: "
    "{ok, say, ...data} or {ok: false, error, say}. Read 'say' to the customer word for word. "
    "Tools that move money or open an account never act on their own: request_transfer, "
    "transfer_between_accounts, pay_bill, pay_loan, withdraw, deposit, and create_account only prepare "
    "the request and return its transfer_id. Only call confirm_payment(transfer_id) after the "
    "customer clearly says yes; if they say no, call cancel_payment(transfer_id). "
    "Accounts, bills, and loans are named the way the customer says them; there are no IDs to look up. "
    "Never make up balances, amounts, payees, bills, loans, or purchases. "
    "If a request is stopped as a possible scam, do not argue or offer "
    "workarounds; tell them to call Capital One."
)


async def _run(fn: Callable[..., Any], *args) -> Any:
    """Bank calls Nessie over the network; keep that off the event loop."""
    return await anyio.to_thread.run_sync(lambda: fn(*args))


# Added to every tool description: ElevenLabs passes these to the model on each turn.
GROUNDING = (
    " Never make up balances, amounts, payees, bills, loans, or purchases: only say what this tool returned."
    " If ok is false, read 'say' and do not guess."
)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _money(amount: Any) -> str:
    return f"${float(amount or 0):,.2f}"


def _day(date: Any) -> str:
    """'2026-10-17' -> 'October 17', the way the agent should say it."""
    try:
        d = datetime.strptime(str(date)[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{d:%B} {d.day}"


def _on(date: Any) -> str:
    day = _day(date)
    return f" on {day}" if day else ""


def _and(items: List[str]) -> str:
    """'a', 'a and b', 'a, b, and c'."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])}{',' if len(items) > 2 else ''} and {items[-1]}"


def _newest(noun: str, items: List[str], extra: str = "") -> str:
    """Name up to three items aloud, newest first, and say how many more there are."""
    how_many = noun if len(items) == 1 else _count(len(items), noun)
    said = f"Your last {how_many}{extra}: {_and(items[:3])}."
    if len(items) > 3:
        said += f" I can read the other {len(items) - 3}."
    return said


def create_app(bank: Bank, allowed_origins: Optional[list] = None) -> Tuple[MCPServer, Starlette]:
    mcp = MCPServer(name="capital-one-voice", instructions=INSTRUCTIONS)

    def tool(description: str):
        return mcp.tool(description=description + GROUNDING)

    # ---- MCP tools (the agent) ----------------------------------------------------
    # Every tool replies with one JSON object:
    #   {"ok": true,  "say": "<read this aloud>", ...data}
    #   {"ok": false, "error": "<what went wrong>", "say": "<read this aloud>"}

    def ok(say: str, **data: Any) -> str:
        return json.dumps({"ok": True, "say": say, **data})

    def failed(err: BankError, money_tool: bool) -> str:
        # "No money was moved" only when that's certain.
        sure = money_tool and not isinstance(err, PaymentUnknown)
        say = f"{err} {NO_MONEY_MOVED}" if sure else str(err)
        return json.dumps({"ok": False, "error": str(err), "say": say})

    # ---- Read tools ----

    @tool("The customer's balance and bills that are due. Replies with JSON: ok, say, summary.")
    async def get_summary() -> str:
        try:
            summary = await _run(bank.summary)
        except BankError as err:
            return failed(err, money_tool=False)
        return ok(f"Your {summary['account_name'].lower()} balance is ${summary['balance']:,.2f}.", summary=summary)

    @tool("Every account the customer has (checking, savings, ...) with its balance. Replies with JSON: ok, say, accounts.")
    async def list_accounts() -> str:
        try:
            accounts = await _run(bank.list_accounts)
        except BankError as err:
            return failed(err, money_tool=False)
        names = ", ".join(f"{a['name']} with ${float(a['balance'] or 0):,.2f}" for a in accounts)
        return ok(f"You have {_count(len(accounts), 'account')}: {names}.", accounts=accounts)

    @tool((
        "The customer's purchases from all accounts, newest first. Optional: merchant_name to show only one "
        "store (e.g. 'CVS'), account_name to show only one account (e.g. 'credit card'). "
        "Replies with JSON: ok, say, purchases (description, amount, date, account)."
    ))
    async def get_recent_purchases(limit: int = 10, merchant_name: str = "", account_name: str = "") -> str:
        try:
            purchases = await _run(bank.recent_purchases, limit, merchant_name, account_name)
        except BankError as err:
            return failed(err, money_tool=False)
        store = f" from {merchant_name.strip()}" if merchant_name.strip() else ""
        if not purchases:
            return ok(f"I don't see any purchases{store}.", purchases=purchases)
        items = [f"{p['description'] or 'a purchase'} for {_money(p['amount'])}{_on(p['date'])}" for p in purchases]
        return ok(_newest("purchase", items, store), purchases=purchases)

    def cash_item(row: dict) -> str:
        return f"{row['description'] or 'no description'} for {_money(row['amount'])}{_on(row['date'])}"

    def transfer_item(row: dict) -> str:
        to = f" to {row['to']}" if row["to"] else (f" for {row['description']}" if row["description"] else "")
        return f"{_money(row['amount'])}{to}{_on(row['date'])}"

    async def latest(fn: Callable[..., Any], noun: str, item: Callable[[dict], str],
                     account_name: str, limit: int) -> str:
        """Deposits, withdrawals, or transfers, newest first, with the first few read aloud."""
        try:
            rows = await _run(fn, account_name, limit)
        except BankError as err:
            return failed(err, money_tool=False)
        if not rows:
            return ok(f"I don't see any {noun}s.", **{f"{noun}s": rows})
        return ok(_newest(noun, [item(r) for r in rows]), **{f"{noun}s": rows})

    @tool((
        "Money put into the customer's accounts, newest first. Optional account_name (e.g. 'savings'). "
        "Replies with JSON: ok, say, deposits (account, description, amount, date, status)."
    ))
    async def get_deposits(account_name: str = "", limit: int = 10) -> str:
        return await latest(bank.deposits, "deposit", cash_item, account_name, limit)

    @tool((
        "Money taken out of the customer's accounts (cash, bill and loan payments), newest first. "
        "Optional account_name. Replies with JSON: ok, say, withdrawals (account, description, amount, date, status)."
    ))
    async def get_withdrawals(account_name: str = "", limit: int = 10) -> str:
        return await latest(bank.withdrawals, "withdrawal", cash_item, account_name, limit)

    @tool((
        "Transfers the customer made, to people or between their own accounts, newest first. Optional account_name. "
        "Replies with JSON: ok, say, transfers (from, to, amount, date, description, status); "
        "'from' and 'to' are account or payee names, or null when unknown."
    ))
    async def get_transfers(account_name: str = "", limit: int = 10) -> str:
        return await latest(bank.transfers, "transfer", transfer_item, account_name, limit)

    @tool((
        "The customer's bills, soonest first. By default only bills still due; include_paid=true adds paid and "
        "cancelled ones. recurring=true shows only repeating bills, recurring=false only one-time bills; leave it "
        "out for both. Optional account_name. "
        "Replies with JSON: ok, say, bills (biller_name, amount, due_date, status, recurring, account)."
    ))
    async def get_bills(account_name: str = "", recurring: Optional[bool] = None, include_paid: bool = False) -> str:
        try:
            bills = await _run(bank.bills, account_name, recurring, include_paid)
        except BankError as err:
            return failed(err, money_tool=False)
        label = {True: "repeating bill", False: "one-time bill", None: "bill"}[recurring]
        if include_paid:
            say = f"I found {_count(len(bills), label)}." if bills else f"I don't see any {label}s."
        elif bills:
            due = [f"{b['biller_name']} for {_money(b['amount'])}"
                   + (f", due {_day(b['due_date'])}" if _day(b["due_date"]) else "") for b in bills]
            say = f"You have {_count(len(bills), label)} due: {_and(due)}."
        else:
            say = f"You have no {label}s due."
        return ok(say, bills=bills)

    @tool((
        "The customer's loans: what is still owed and the usual monthly payment. "
        "Replies with JSON: ok, say, loans (name, amount_owed, monthly_payment, status, description, account)."
    ))
    async def get_loans() -> str:
        try:
            loans = await _run(bank.loans)
        except BankError as err:
            return failed(err, money_tool=False)
        if not loans:
            return ok("You don't have any loans.", loans=loans)
        listed = ", ".join(f"your {loan['name'].lower()} with ${float(loan['amount_owed'] or 0):,.2f} still owed"
                           for loan in loans)
        return ok(f"You have {_count(len(loans), 'loan')}: {listed}.", loans=loans)

    @tool((
        "Look up a store the customer has bought from by name (e.g. 'Corner Cafe'): its category and address. "
        "Only searches the merchants on the customer's own purchases. "
        "Replies with JSON: ok, say, merchants (name, category, address)."
    ))
    async def find_merchant(name: str) -> str:
        try:
            merchants = await _run(bank.find_merchant, name)
        except BankError as err:
            return failed(err, money_tool=False)
        if not merchants:
            return ok(f"I couldn't find a store called {name} in your purchases.", merchants=merchants)
        if len(merchants) == 1:
            m = merchants[0]
            where = f", at {m['address']}" if m["address"] else ""
            return ok(f"I found {m['name']}{where}.", merchants=merchants)
        return ok(f"I found {len(merchants)} stores: {', '.join(m['name'] for m in merchants)}.", merchants=merchants)

    # ---- Money tools: each only prepares a request; confirm_payment carries it out ----

    async def prepare(fn: Callable[..., Any], *args) -> str:
        try:
            t = await _run(fn, *args)
        except BankError as err:
            return failed(err, money_tool=True)
        return ok(t["spoken_message"], transfer=t)

    @tool((
        "Prepare a transfer to someone the customer names. Does NOT send money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer (transfer_id, status, decision, "
        "risk_score, reasons, ...). If transfer.status is 'held', the payment is stopped for good."
    ))
    async def request_transfer(payee_name: str, amount: float, memo: str = "") -> str:
        return await prepare(bank.request_transfer, payee_name, amount, memo)

    @tool((
        "Prepare moving money between two of the customer's own accounts, named the way they say them "
        "(e.g. from_account 'savings', to_account 'checking'). Does NOT move money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer. If transfer.status is 'held', it is stopped for good."
    ))
    async def transfer_between_accounts(from_account: str, to_account: str, amount: float, memo: str = "") -> str:
        return await prepare(bank.transfer_between_accounts, from_account, to_account, amount, memo)

    @tool((
        "Prepare a bill payment by biller name, e.g. 'Pepco'. Leave amount out to pay the bill in full, or give a "
        "smaller amount to pay part of it; it can't be more than is owed. Money comes from checking unless "
        "from_account names another account. Does NOT send money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer."
    ))
    async def pay_bill(biller_name: str, amount: Optional[float] = None, from_account: str = "") -> str:
        return await prepare(bank.pay_bill, biller_name, amount, from_account)

    @tool((
        "Prepare a loan payment, e.g. loan_name 'auto'. Leave loan_name out if the customer has one loan. "
        "Leave amount out to pay the usual monthly payment; it can't be more than is still owed. Money comes from "
        "checking unless from_account names another account. Does NOT send money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer."
    ))
    async def pay_loan(loan_name: str = "", amount: Optional[float] = None, from_account: str = "") -> str:
        return await prepare(bank.pay_loan, loan_name, amount, from_account)

    @tool((
        "Prepare a cash withdrawal from the customer's account. Does NOT move money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer. If transfer.status is 'held', it is stopped for good."
    ))
    async def withdraw(amount: float, memo: str = "") -> str:
        return await prepare(bank.withdraw, amount, memo)

    @tool((
        "Prepare a deposit into the customer's account. Does NOT move money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer."
    ))
    async def deposit(amount: float, memo: str = "") -> str:
        return await prepare(bank.deposit, amount, memo)

    @tool((
        "Prepare opening a new account with a $0 balance. account_type is 'Checking', 'Savings', or 'Credit Card'; "
        "nickname is optional. Does NOT open it: it gets the same scam check as a payment and needs a yes. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer. If transfer.status is 'held', it is stopped for good."
    ))
    async def create_account(account_type: str, nickname: str = "") -> str:
        return await prepare(bank.create_account, account_type, nickname)

    @tool((
        "Carry out the request that is waiting for a yes. Only call this after the customer clearly says yes. "
        "Pass transfer.transfer_id from request_transfer, transfer_between_accounts, pay_bill, pay_loan, withdraw, "
        "deposit, or create_account. Replies with JSON: ok, say, transfer."
    ))
    async def confirm_payment(transfer_id: str) -> str:
        try:
            t = await _run(bank.confirm, transfer_id)
        except BankError as err:
            return failed(err, money_tool=True)
        if t["kind"] == "new_account":
            return ok(f"Done. Your new {t['account_type'].lower()} account is open. "
                      "Is there anything else I can help with?", transfer=t)
        account, payee = account_phrase(t["from_account_name"]), t["payee_name"]
        what = {"withdrawal": f"taken out of your {account} account",
                "deposit": f"added to your {account} account",
                "own_transfer": f"moved from your {account} account to your {account_phrase(payee)} account",
                "loan": f"paid toward your {payee.lower()}"}.get(t["kind"], f"sent to {payee}")
        owed = t.get("amount_owed")
        rest = (f" {_money(owed - t['amount'])} is still due."
                if t["kind"] == "bill" and owed is not None and t["amount"] < owed else "")
        return ok(f"Done. ${t['amount']:,.2f} has been {what}.{rest} Is there anything else I can help with?",
                  transfer=t)

    @tool("Cancel the request that is waiting for a yes, when the customer says no. Replies with JSON.")
    async def cancel_payment(transfer_id: str) -> str:
        try:
            t = await _run(bank.cancel, transfer_id)
        except BankError as err:
            return failed(err, money_tool=False)
        undone = "open it" if t["kind"] == "new_account" else "send it"
        return ok(f"Okay, I didn't {undone}. {NO_MONEY_MOVED}", transfer=t)

    # ---- App endpoints (the screen) ------------------------------------------------

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise BankError("The request body must be JSON.")
        if not isinstance(data, dict):
            raise BankError("The request body must be a JSON object.")
        return data

    def error(message: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    @mcp.custom_route("/api/transcript", methods=["POST"])
    async def transcript(request: Request) -> JSONResponse:
        try:
            data = await body(request)
        except BankError as err:
            return error(str(err))
        conversation_id, text = data.get("conversation_id"), data.get("text")
        if not isinstance(conversation_id, str) or not isinstance(text, str):
            return error("conversation_id and text are required.")
        bank.add_transcript_line(conversation_id, text)
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api/transfer/current", methods=["GET"])
    async def current(request: Request) -> JSONResponse:
        return JSONResponse({"transfer": bank.current()})

    @mcp.custom_route("/api/transfer/confirm", methods=["POST"])
    async def confirm(request: Request) -> JSONResponse:
        try:
            t = await _run(bank.confirm, (await body(request)).get("transfer_id", ""))
        except BankError as err:
            return error(str(err))
        return JSONResponse({"status": t["status"]})

    @mcp.custom_route("/api/transfer/cancel", methods=["POST"])
    async def cancel(request: Request) -> JSONResponse:
        try:
            t = await _run(bank.cancel, (await body(request)).get("transfer_id", ""))
        except BankError as err:
            return error(str(err))
        return JSONResponse({"status": t["status"]})

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    # Stateless HTTP so it works behind a load balancer or on serverless hosts.
    # host="0.0.0.0" turns off the SDK's localhost-only Host check, which would block ElevenLabs.
    app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or ["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    return mcp, app


def origins_from_env() -> Optional[list]:
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    return [o.strip() for o in raw.split(",") if o.strip()] or None
