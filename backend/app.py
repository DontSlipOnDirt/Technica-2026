# app.py
# One web app with two doors into the same Bank:
#   /mcp      - the MCP server the ElevenLabs agent connects to (streamable HTTP)
#   /api/...  - the endpoints the voice screen calls (transcript, current transfer, Yes/No)
# Replaces Jacob's stdio TypeScript server: ElevenLabs can only reach MCP servers over HTTP.

import json
import os
from typing import Any, Callable, Optional, Tuple

import anyio
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from bank import Bank, BankError

NO_MONEY_MOVED = "No money was moved."

INSTRUCTIONS = (
    "Banking tools for a Capital One voice assistant. Every tool replies with JSON: "
    "{ok, say, ...data} or {ok: false, error, say}. Read 'say' to the customer word for word. "
    "Money tools never move money on their own: request_transfer and pay_bill only prepare a payment "
    "and return its transfer_id. Only call confirm_payment(transfer_id) after the "
    "customer clearly says yes. Never make up balances, amounts, payees, bills, or purchases. "
    "If a payment is stopped as a possible scam, do not argue or offer "
    "workarounds; tell them to call Capital One."
)


async def _run(fn: Callable[..., Any], *args) -> Any:
    """Bank calls Nessie over the network; keep that off the event loop."""
    return await anyio.to_thread.run_sync(lambda: fn(*args))


# Added to every tool description: ElevenLabs passes these to the model on each turn.
GROUNDING = (
    " Never make up balances, amounts, payees, bills, or purchases: only say what this tool returned."
    " If ok is false, read 'say' and do not guess."
)


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
        say = f"{err} {NO_MONEY_MOVED}" if money_tool else str(err)
        return json.dumps({"ok": False, "error": str(err), "say": say})

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
        return ok(f"You have {len(accounts)} account{'s' if len(accounts) != 1 else ''}: {names}.", accounts=accounts)

    @tool("The customer's most recent purchases, newest first. Replies with JSON: ok, say, purchases.")
    async def get_recent_purchases(limit: int = 10) -> str:
        try:
            purchases = await _run(bank.recent_purchases, limit)
        except BankError as err:
            return failed(err, money_tool=False)
        return ok(f"Here are your last {len(purchases)} purchases.", purchases=purchases)

    @tool((
        "Prepare a transfer to someone the customer names. Does NOT send money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer (transfer_id, status, decision, "
        "risk_score, reasons, ...). If transfer.status is 'held', the payment is stopped for good."
    ))
    async def request_transfer(payee_name: str, amount: float, memo: str = "") -> str:
        try:
            t = await _run(bank.request_transfer, payee_name, amount, memo)
        except BankError as err:
            return failed(err, money_tool=True)
        return ok(t["spoken_message"], transfer=t)

    @tool((
        "Prepare a bill payment by biller name, e.g. 'Pepco'. Leave amount out to pay the bill in full. "
        "Does NOT send money. Replies with JSON: ok, say (read it aloud exactly), transfer."
    ))
    async def pay_bill(biller_name: str, amount: Optional[float] = None) -> str:
        try:
            t = await _run(bank.pay_bill, biller_name, amount)
        except BankError as err:
            return failed(err, money_tool=True)
        return ok(t["spoken_message"], transfer=t)

    @tool((
        "Prepare a cash withdrawal from the customer's account. Does NOT move money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer. If transfer.status is 'held', it is stopped for good."
    ))
    async def withdraw(amount: float, memo: str = "") -> str:
        try:
            t = await _run(bank.withdraw, amount, memo)
        except BankError as err:
            return failed(err, money_tool=True)
        return ok(t["spoken_message"], transfer=t)

    @tool((
        "Prepare a deposit into the customer's account. Does NOT move money. "
        "Replies with JSON: ok, say (read it aloud exactly), transfer."
    ))
    async def deposit(amount: float, memo: str = "") -> str:
        try:
            t = await _run(bank.deposit, amount, memo)
        except BankError as err:
            return failed(err, money_tool=True)
        return ok(t["spoken_message"], transfer=t)

    @tool((
        "Send the payment that is waiting for a yes. Only call this after the customer clearly says yes. "
        "Pass transfer.transfer_id from request_transfer, pay_bill, withdraw, or deposit. Replies with JSON: ok, say, transfer."
    ))
    async def confirm_payment(transfer_id: str) -> str:
        try:
            t = await _run(bank.confirm, transfer_id)
        except BankError as err:
            return failed(err, money_tool=True)
        account = t["from_account_name"].lower()
        what = {"withdrawal": f"taken out of your {account} account",
                "deposit": f"added to your {account} account"}.get(t["kind"], f"sent to {t['payee_name']}")
        return ok(f"Done. ${t['amount']:,.2f} has been {what}. Is there anything else I can help with?", transfer=t)

    @tool("Cancel the payment that is waiting for a yes, when the customer says no. Replies with JSON.")
    async def cancel_payment(transfer_id: str) -> str:
        try:
            t = await _run(bank.cancel, transfer_id)
        except BankError as err:
            return failed(err, money_tool=False)
        return ok(f"Okay, I didn't send it. {NO_MONEY_MOVED}", transfer=t)

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
