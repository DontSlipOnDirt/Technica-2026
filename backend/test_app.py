import json

import pytest
from starlette.testclient import TestClient

import fraud_check
from app import create_app
from bank import Bank
from nessie import NessieApiError
from test_bank import ACCOUNT, CONFIG, SAVINGS, FakeNessie, auto_loan


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


def tool_json(result) -> dict:
    """Every tool replies with one JSON object."""
    return json.loads(tool_text(result))


# ---- MCP tools: what the agent hears (always JSON) ----------------------------------

async def test_request_transfer_returns_json_with_the_transfer_id(setup):
    _, bank, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("request_transfer", {"payee_name": "Maria", "amount": 50}))
    assert reply["ok"] is True
    assert reply["say"].startswith("I'll pay Maria $50.00")
    assert reply["transfer"]["transfer_id"] == bank.current()["transfer_id"]
    assert reply["transfer"]["status"] == "awaiting_yes"
    assert reply["transfer"]["decision"] == "allow"
    assert "risk_score" in reply["transfer"] and "reasons" in reply["transfer"]


async def test_held_request_says_so_in_json(setup):
    _, bank, mcp, _ = setup
    bank.add_transcript_line("c1", "move it to a safe account right now")
    reply = tool_json(await mcp.call_tool("request_transfer", {"payee_name": "Bob", "amount": 2000}))
    assert reply["ok"] is True
    assert reply["transfer"]["status"] == "held"
    assert reply["transfer"]["decision"] == "hold"
    assert "Capital One will never ask" in reply["say"]


async def test_confirm_payment_sends_and_says_done(setup):
    nessie, bank, mcp, _ = setup
    t = bank.request_transfer("Maria", 50)
    reply = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": t["transfer_id"]}))
    assert reply["ok"] is True
    assert reply["transfer"]["status"] == "executed"
    assert reply["say"].startswith("Done.")
    assert len(nessie.posted) == 1


async def test_confirm_payment_on_a_hold_is_refused(setup):
    nessie, bank, mcp, _ = setup
    bank.add_transcript_line("c1", "move it to a safe account right now")
    t = bank.request_transfer("Bob", 2000)
    reply = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": t["transfer_id"]}))
    assert reply == {"ok": False, "error": "That payment can't be sent.",
                     "say": "That payment can't be sent. No money was moved."}
    assert nessie.posted == []


async def test_unknown_payee_says_no_money_moved(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("request_transfer", {"payee_name": "Zed", "amount": 5}))
    assert reply["ok"] is False
    assert "Zed" in reply["error"] and reply["say"].endswith("No money was moved.")


async def test_pay_bill_and_cancel(setup):
    _, bank, mcp, _ = setup
    bill = tool_json(await mcp.call_tool("pay_bill", {"biller_name": "pepco"}))
    assert bill["transfer"]["payee_name"] == "Pepco" and bill["transfer"]["kind"] == "bill"
    reply = tool_json(await mcp.call_tool("cancel_payment", {"transfer_id": bill["transfer"]["transfer_id"]}))
    assert reply["ok"] is True and reply["transfer"]["status"] == "cancelled"
    assert reply["say"].endswith("No money was moved.")


async def test_get_summary_is_json_the_agent_can_read(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("get_summary", {}))
    assert reply["ok"] is True
    assert reply["summary"]["balance"] == 3000.0


async def test_get_recent_purchases_is_json(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("get_recent_purchases", {}))
    assert reply["ok"] is True
    assert reply["purchases"][0]["amount"] == 86.40


async def test_there_is_no_tool_that_moves_money_directly(setup):
    _, _, mcp, _ = setup
    names = {t.name for t in await mcp.list_tools()}
    assert names == {
        # Read only
        "get_summary", "list_accounts", "get_recent_purchases", "get_deposits", "get_withdrawals", "get_transfers",
        "get_bills", "get_loans", "find_merchant",
        # Prepare only: each returns a transfer_id and waits for a yes
        "request_transfer", "transfer_between_accounts", "pay_bill", "pay_loan", "withdraw", "deposit",
        "create_account",
        # The yes and the no: confirm_payment is still the only tool that moves money
        "confirm_payment", "cancel_payment",
    }


async def test_every_money_tool_only_prepares(setup):
    nessie, bank, mcp, _ = setup
    nessie.loans = [auto_loan()]
    calls = {
        "request_transfer": {"payee_name": "Maria", "amount": 50},
        "transfer_between_accounts": {"from_account": "savings", "to_account": "checking", "amount": 50},
        "pay_bill": {"biller_name": "Pepco", "amount": 50},
        "pay_loan": {"loan_name": "auto"},
        "withdraw": {"amount": 40},
        "deposit": {"amount": 25},
        "create_account": {"account_type": "Savings"},
    }
    for name, args in calls.items():
        reply = tool_json(await mcp.call_tool(name, args))
        assert reply["ok"] is True, (name, reply)
        assert reply["transfer"]["status"] == "awaiting_yes", name
        assert reply["transfer"]["transfer_id"] == bank.current()["transfer_id"], name
    assert nessie.posted == [] and nessie.puts == []


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
    down = {"ok": False, "error": "I couldn't reach the bank right now.", "say": "I couldn't reach the bank right now."}
    assert tool_json(await mcp.call_tool("get_summary", {})) == down
    assert tool_json(await mcp.call_tool("get_recent_purchases", {})) == down
    reply = tool_json(await mcp.call_tool("request_transfer", {"payee_name": "Maria", "amount": 50}))
    assert reply["say"] == "I couldn't reach the bank right now. No money was moved."


async def test_every_tool_tells_the_agent_not_to_make_things_up(setup):
    _, _, mcp, _ = setup
    for tool in await mcp.list_tools():
        assert "Never make up" in tool.description, tool.name


async def test_list_accounts_tool(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("list_accounts", {}))
    assert reply["ok"] is True
    assert [a["name"] for a in reply["accounts"]] == ["Checking", "Rainy day"]


async def test_withdraw_then_confirm_says_done(setup):
    nessie, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("withdraw", {"amount": 40}))
    assert reply["transfer"]["status"] == "awaiting_yes"
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert done["say"].startswith("Done. $40.00 has been taken out of your checking account")
    assert nessie.posted[0][0].endswith("/withdrawals")


async def test_deposit_then_confirm_says_done(setup):
    nessie, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("deposit", {"amount": 25}))
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert done["say"].startswith("Done. $25.00 has been added to your checking account")
    assert nessie.posted[0][0].endswith("/deposits")


# ---- Read tools added from the Nessie-framework server ------------------------------

async def test_get_bills_says_what_is_due(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("get_bills", {}))
    assert reply["say"] == "You have 1 bill due: Pepco for $600.00."
    assert reply["bills"][0]["biller_name"] == "Pepco"
    assert tool_json(await mcp.call_tool("get_bills", {"recurring": True}))["say"] == "You have no repeating bills due."
    assert tool_json(await mcp.call_tool("get_bills", {"include_paid": True}))["say"] == "I found 1 bill."


async def test_get_loans_says_what_is_owed(setup):
    nessie, _, mcp, _ = setup
    assert tool_json(await mcp.call_tool("get_loans", {}))["say"] == "You don't have any loans."
    nessie.loans = [auto_loan()]
    reply = tool_json(await mcp.call_tool("get_loans", {}))
    assert reply["say"] == "You have 1 loan: your auto loan with $4,200.00 still owed."
    assert reply["loans"][0]["monthly_payment"] == 350


async def test_history_tools_reply_with_json(setup):
    nessie, _, mcp, _ = setup
    nessie.deposits = [{"amount": 1450, "transaction_date": "2026-10-03", "description": "Social Security"}]
    deposits = tool_json(await mcp.call_tool("get_deposits", {}))
    assert deposits["say"] == "Your last deposit: Social Security for $1,450.00 on October 3."
    assert deposits["deposits"][0]["amount"] == 1450
    withdrawals = tool_json(await mcp.call_tool("get_withdrawals", {"account_name": "savings"}))
    assert withdrawals == {"ok": True, "say": "I don't see any withdrawals.", "withdrawals": []}
    transfers = tool_json(await mcp.call_tool("get_transfers", {}))
    assert transfers["transfers"][0]["to"] == "Maria"


async def test_an_unknown_account_name_is_a_sentence(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("get_deposits", {"account_name": "brokerage"}))
    assert reply == {"ok": False, "error": "I couldn't find an account called brokerage.",
                     "say": "I couldn't find an account called brokerage."}


async def test_purchases_by_merchant_and_merchant_lookup(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("get_recent_purchases", {"merchant_name": "Giant"}))
    assert reply["say"] == "Your last purchase from Giant: Giant for $86.40 on October 15."
    assert reply["purchases"][0]["amount"] == 86.40
    found = tool_json(await mcp.call_tool("find_merchant", {"name": "giant"}))
    assert found["say"] == "I found Giant Food, at 4500 Knox Rd, College Park, MD 20740."
    assert found["merchants"] == [{"name": "Giant Food", "category": "Grocery",
                                   "address": "4500 Knox Rd, College Park, MD 20740"}]
    missing = tool_json(await mcp.call_tool("find_merchant", {"name": "Target"}))
    assert missing["say"] == "I couldn't find a store called Target in your purchases."


# ---- Money tools added from the Nessie-framework server ------------------------------

async def test_move_between_accounts_then_confirm_says_moved(setup):
    nessie, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("transfer_between_accounts",
                                          {"from_account": "checking", "to_account": "savings", "amount": 100}))
    assert reply["say"] == "I'll move $100.00 from your checking account to your Rainy day account. Are you sure?"
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert done["say"].startswith("Done. $100.00 has been moved from your checking account to your Rainy day account.")
    assert [path for path, _ in nessie.posted] == [f"/accounts/{ACCOUNT}/withdrawals", f"/accounts/{SAVINGS}/deposits"]


async def test_pay_loan_then_confirm_says_paid(setup):
    nessie, _, mcp, _ = setup
    nessie.loans = [auto_loan()]
    reply = tool_json(await mcp.call_tool("pay_loan", {}))
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert done["say"].startswith("Done. $350.00 has been paid toward your auto loan.")
    assert nessie.puts == [("/loans/loan-1", {"amount": 3850})]


async def test_paying_more_than_a_bill_is_refused(setup):
    nessie, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("pay_bill", {"biller_name": "Pepco", "amount": 700}))
    assert reply == {"ok": False, "error": "That's more than the $600.00 you owe Pepco.",
                     "say": "That's more than the $600.00 you owe Pepco. No money was moved."}


async def test_create_account_needs_a_yes(setup):
    nessie, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("create_account", {"account_type": "Savings", "nickname": "Travel"}))
    assert reply["say"] == "I'll open a new savings account called Travel, with a $0.00 balance. Are you sure?"
    cancelled = tool_json(await mcp.call_tool("cancel_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert cancelled["say"] == "Okay, I didn't open it. No money was moved."
    again = tool_json(await mcp.call_tool("create_account", {"account_type": "Savings", "nickname": "Travel"}))
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": again["transfer"]["transfer_id"]}))
    assert done["say"] == "Done. Your new savings account is open. Is there anything else I can help with?"
    assert nessie.posted == [("/customers/cust-rose/accounts",
                              {"type": "Savings", "nickname": "Travel", "rewards": 0, "balance": 0})]


async def test_part_of_a_bill_says_what_is_still_due(setup):
    _, _, mcp, _ = setup
    reply = tool_json(await mcp.call_tool("pay_bill", {"biller_name": "Pepco", "amount": 200}))
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert done["say"] == ("Done. $200.00 has been sent to Pepco. $400.00 is still due. "
                           "Is there anything else I can help with?")


async def test_an_unknown_outcome_never_says_no_money_moved(setup):
    nessie, _, mcp, _ = setup
    nessie.fail_paths["/withdrawals"] = NessieApiError("Nessie request timed out", 408, outcome_unknown=True)
    reply = tool_json(await mcp.call_tool("request_transfer", {"payee_name": "Maria", "amount": 50}))
    done = tool_json(await mcp.call_tool("confirm_payment", {"transfer_id": reply["transfer"]["transfer_id"]}))
    assert done["ok"] is False
    assert "not sure that payment went through" in done["say"]
    assert "No money was moved" not in done["say"]


async def test_read_replies_name_the_details_not_just_a_count(setup):
    nessie, _, mcp, _ = setup
    nessie.purchases = [
        {"amount": 54.20, "purchase_date": "2026-10-17", "description": "Fresh Market"},
        {"amount": 18.75, "purchase_date": "2026-10-16", "description": "CVS Pharmacy"},
        {"amount": 9.50, "purchase_date": "2026-10-14", "description": "Corner Cafe [cat:Food]"},
        {"amount": 71.10, "purchase_date": "2026-10-09", "description": "Fresh Market"},
    ]
    nessie.bills[0]["payment_date"] = "2026-10-24"
    purchases = tool_json(await mcp.call_tool("get_recent_purchases", {"limit": 5}))
    assert purchases["say"] == ("Your last 4 purchases: Fresh Market for $54.20 on October 17, CVS Pharmacy for "
                                "$18.75 on October 16, and Corner Cafe for $9.50 on October 14. "
                                "I can read the other 1.")
    bills = tool_json(await mcp.call_tool("get_bills", {}))
    assert bills["say"] == "You have 1 bill due: Pepco for $600.00, due October 24."
    transfers = tool_json(await mcp.call_tool("get_transfers", {}))
    assert transfers["say"] == "Your last transfer: $100.00 to Maria on October 1."


def test_the_screen_sees_which_kind_of_request_is_waiting(setup):
    _, bank, _, app = setup
    bank.create_account("Savings", "Travel")
    with TestClient(app) as client:
        t = client.get("/api/transfer/current").json()["transfer"]
    assert (t["kind"], t["account_type"], t["payee_name"], t["amount"]) == ("new_account", "Savings", "Travel", 0)
