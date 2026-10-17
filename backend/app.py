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
    "Banking tools for a Capital One voice assistant. Read-only tools answer questions. "
    "Money tools never move money on their own: request_transfer and pay_bill only prepare a payment "
    "and return a sentence to read to the customer word for word. Only call confirm_payment after the "
    "customer clearly says yes. If a payment is stopped as a possible scam, do not argue or offer "
    "workarounds; tell them to call Capital One."
)


async def _run(fn: Callable[..., Any], *args) -> Any:
    """Bank calls Nessie over the network; keep that off the event loop."""
    return await anyio.to_thread.run_sync(lambda: fn(*args))


def create_app(bank: Bank, allowed_origins: Optional[list] = None) -> Tuple[MCPServer, Starlette]:
    mcp = MCPServer(name="capital-one-voice", instructions=INSTRUCTIONS)

    # ---- MCP tools (the agent) ----------------------------------------------------

    @mcp.tool(description="The customer's balance and bills that are due. Returns JSON.")
    async def get_summary() -> str:
        try:
            return json.dumps(await _run(bank.summary))
        except BankError as err:
            return str(err)

    @mcp.tool(description="The customer's most recent purchases, newest first. Returns JSON.")
    async def get_recent_purchases(limit: int = 10) -> str:
        try:
            return json.dumps(await _run(bank.recent_purchases, limit))
        except BankError as err:
            return str(err)

    @mcp.tool(description=(
        "Prepare a transfer to someone the customer names. Does NOT send money. "
        "Read the returned sentence to the customer exactly as written."
    ))
    async def request_transfer(payee_name: str, amount: float, memo: str = "") -> str:
        try:
            return (await _run(bank.request_transfer, payee_name, amount, memo))["spoken_message"]
        except BankError as err:
            return f"{err} {NO_MONEY_MOVED}"

    @mcp.tool(description=(
        "Prepare a bill payment by biller name, e.g. 'Pepco'. Leave amount out to pay the bill in full. "
        "Does NOT send money. Read the returned sentence to the customer exactly as written."
    ))
    async def pay_bill(biller_name: str, amount: Optional[float] = None) -> str:
        try:
            return (await _run(bank.pay_bill, biller_name, amount))["spoken_message"]
        except BankError as err:
            return f"{err} {NO_MONEY_MOVED}"

    @mcp.tool(description=(
        "Send the payment that is waiting for a yes. Only call this after the customer clearly says yes. "
        "Use the transfer_id of the current payment."
    ))
    async def confirm_payment(transfer_id: str) -> str:
        try:
            t = await _run(bank.confirm, transfer_id)
        except BankError as err:
            return f"{err} {NO_MONEY_MOVED}"
        return f"Done. ${t['amount']:,.2f} has been sent to {t['payee_name']}. Ask if there is anything else."

    @mcp.tool(description="Cancel the payment that is waiting for a yes, when the customer says no.")
    async def cancel_payment(transfer_id: str) -> str:
        try:
            await _run(bank.cancel, transfer_id)
        except BankError as err:
            return str(err)
        return f"Okay, I didn't send it. {NO_MONEY_MOVED}"

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
