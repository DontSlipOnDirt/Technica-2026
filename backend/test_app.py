import json

import pytest
from starlette.testclient import TestClient

import fraud_check
from app import create_app
from bank import Bank
from test_bank import CONFIG, FakeNessie


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    monkeypatch.setattr(fraud_check, "scam_signals", lambda said: None)


@pytest.fixture
def setup():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    mcp, app = create_app(bank)
    return nessie, bank, mcp, app


def tool_text(result) -> str:
    """call_tool returns content blocks (and maybe structured output); pull out the text."""
    blocks = result[0] if isinstance(result, tuple) else getattr(result, "content", result)
    return "".join(getattr(b, "text", "") for b in blocks)


# ---- MCP tools: what the agent hears ----------------------------------------------

async def test_request_transfer_returns_the_spoken_message(setup):
    _, bank, mcp, _ = setup
    text = tool_text(await mcp.call_tool("request_transfer", {"payee_name": "Maria", "amount": 50}))
    assert text.startswith("I'll pay Maria $50.00")
    assert bank.current()["status"] == "awaiting_yes"


async def test_confirm_payment_sends_and_says_done(setup):
    nessie, bank, mcp, _ = setup
    t = bank.request_transfer("Maria", 50)
    text = tool_text(await mcp.call_tool("confirm_payment", {"transfer_id": t["transfer_id"]}))
    assert text.startswith("Done.")
    assert len(nessie.posted) == 1


async def test_confirm_payment_on_a_hold_is_refused(setup):
    nessie, bank, mcp, _ = setup
    bank.add_transcript_line("c1", "move it to a safe account right now")
    t = bank.request_transfer("Bob", 2000)
    text = tool_text(await mcp.call_tool("confirm_payment", {"transfer_id": t["transfer_id"]}))
    assert text.endswith("No money was moved.")
    assert nessie.posted == []


async def test_unknown_payee_says_no_money_moved(setup):
    _, _, mcp, _ = setup
    text = tool_text(await mcp.call_tool("request_transfer", {"payee_name": "Zed", "amount": 5}))
    assert "Zed" in text and text.endswith("No money was moved.")


async def test_pay_bill_and_cancel(setup):
    _, bank, mcp, _ = setup
    assert "Pepco" in tool_text(await mcp.call_tool("pay_bill", {"biller_name": "pepco"}))
    text = tool_text(await mcp.call_tool("cancel_payment", {"transfer_id": bank.current()["transfer_id"]}))
    assert text.endswith("No money was moved.")
    assert bank.current()["status"] == "cancelled"


async def test_get_summary_is_json_the_agent_can_read(setup):
    _, _, mcp, _ = setup
    data = json.loads(tool_text(await mcp.call_tool("get_summary", {})))
    assert data["balance"] == 3000.0


async def test_there_is_no_tool_that_moves_money_directly(setup):
    _, _, mcp, _ = setup
    names = {t.name for t in await mcp.list_tools()}
    assert names == {"get_summary", "get_recent_purchases", "request_transfer", "pay_bill",
                     "confirm_payment", "cancel_payment"}


# ---- App endpoints: what the screen calls -----------------------------------------

def test_transcript_feeds_the_fraud_check(setup):
    _, bank, _, app = setup
    with TestClient(app) as client:
        assert client.post("/api/transcript", json={"conversation_id": "c1", "text": "safe account"}).json() == {"ok": True}
    assert bank.request_transfer("Bob", 400)["status"] == "held"


def test_current_transfer_starts_empty_then_shows_the_request(setup):
    _, bank, _, app = setup
    with TestClient(app) as client:
        assert client.get("/api/transfer/current").json() == {"transfer": None}
        bank.request_transfer("Maria", 50)
        assert client.get("/api/transfer/current").json()["transfer"]["status"] == "awaiting_yes"


def test_confirm_and_cancel_endpoints(setup):
    _, bank, _, app = setup
    with TestClient(app) as client:
        t = bank.request_transfer("Maria", 50)
        assert client.post("/api/transfer/confirm", json={"transfer_id": t["transfer_id"]}).json() == {"status": "executed"}
        res = client.post("/api/transfer/cancel", json={"transfer_id": t["transfer_id"]})
        assert res.status_code == 400
        assert res.json() == {"error": "That payment was already sent."}


def test_confirm_endpoint_refuses_a_hold(setup):
    _, bank, _, app = setup
    bank.add_transcript_line("c1", "safe account")
    t = bank.request_transfer("Bob", 2000)
    with TestClient(app) as client:
        res = client.post("/api/transfer/confirm", json={"transfer_id": t["transfer_id"]})
    assert res.status_code == 400
    assert res.json() == {"error": "That payment can't be sent."}


def test_bad_json_is_a_400(setup):
    _, _, _, app = setup
    with TestClient(app) as client:
        res = client.post("/api/transfer/confirm", content=b"nope", headers={"Content-Type": "application/json"})
    assert res.status_code == 400
    assert "error" in res.json()


def test_mcp_speaks_streamable_http(setup):
    """ElevenLabs connects over HTTP; make sure an MCP initialize works on /mcp."""
    _, _, _, app = setup
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}},
    }
    with TestClient(app) as client:
        res = client.post("/mcp", json=init, headers={"Accept": "application/json, text/event-stream"})
    assert res.status_code == 200
    assert "capital-one-voice" in res.text


class DownNessie(FakeNessie):
    def get(self, path, params=None):
        from nessie import NessieApiError
        raise NessieApiError("Nessie request failed with status 401", 401)


async def test_nessie_down_gives_sentences_not_crashes():
    mcp, _ = create_app(Bank(DownNessie(), CONFIG))
    assert tool_text(await mcp.call_tool("get_summary", {})) == "I couldn't reach the bank right now."
    assert tool_text(await mcp.call_tool("get_recent_purchases", {})) == "I couldn't reach the bank right now."
    text = tool_text(await mcp.call_tool("request_transfer", {"payee_name": "Maria", "amount": 50}))
    assert text == "I couldn't reach the bank right now. No money was moved."
