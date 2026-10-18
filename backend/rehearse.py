# rehearse.py
# Walks the whole demo against a running backend, playing both sides:
#   - the customer: posts what she says to /api/transcript, as the voice screen does
#   - the agent:    calls the MCP tools on /mcp, as ElevenLabs does
#   - her taps:     Yes / No through /api/transfer/confirm|cancel, as the screen's buttons do
# and checks every answer. It covers every tool, the screen, and each scam protection.
#
#   docker run -e DEMO_MODE=true -p 8000:8000 technica-backend    (the built-in pretend bank)
#   python backend/rehearse.py                                     (defaults to http://localhost:8000)
#
# It moves money, so it refuses a non-local server unless you pass --live.
# The pause after "stop" / "wait" lives in the screen, not here; see docs/demo-script.md.

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

BASE = "http://localhost:8000"
results = {"pass": 0, "fail": 0}
conversation = "rehearsal-0"


# ---- The three doors -------------------------------------------------------------

def _post(path: str, body: Dict[str, Any]) -> Any:
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        return json.loads(err.read() or b"{}")


def new_conversation(n: int) -> None:
    """Each scene is its own call, so earlier words don't color the scam check."""
    global conversation
    conversation = f"rehearsal-{n}"


def say(text: str) -> None:
    print(f"\n  CUSTOMER: {text}")
    _post("/api/transcript", {"conversation_id": conversation, "text": text})


def tool(tool_name: str, **args: Any) -> Dict[str, Any]:
    reply = _post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool_name, "arguments": args}})
    data = json.loads(reply["result"]["content"][0]["text"])
    t = data.get("transfer") or {}
    tag = f"   [{t['kind']}: {t['status']}, risk {t['risk_score']}]" if t else ""
    print(f"  AGENT    ({tool_name}): {data['say']}{tag}")
    return data


def screen() -> Optional[Dict[str, Any]]:
    with urllib.request.urlopen(BASE + "/api/transfer/current", timeout=30) as response:
        return json.loads(response.read())["transfer"]


def tap(button: str, data: Dict[str, Any]) -> Dict[str, Any]:
    path = "/api/transfer/confirm" if button == "Yes" else "/api/transfer/cancel"
    answer = _post(path, {"transfer_id": data["transfer"]["transfer_id"]})
    print(f"  SCREEN   she taps {button} -> {answer}")
    return answer


def check(what: str, ok: bool, detail: Any = "") -> None:
    results["pass" if ok else "fail"] += 1
    print(f"    {'PASS' if ok else 'FAIL'}  {what}" + (f"  ({detail})" if detail and not ok else ""))


def balances() -> Dict[str, float]:
    return {a["name"]: float(a["balance"] or 0) for a in tool("list_accounts")["accounts"]}


def scene(n: int, title: str) -> None:
    new_conversation(n)
    print(f"\n=== Scene {n}: {title} " + "=" * max(0, 60 - len(title)))


# ---- The demo ------------------------------------------------------------------------

def run() -> None:
    scene(1, "Getting to know her money")
    say("Hi, how much money do I have?")
    summary = tool("get_summary")
    check("balance comes back as a number", isinstance(summary["summary"]["balance"], (int, float)))
    say("What accounts do I have?")
    accounts = tool("list_accounts")
    check("lists at least checking and savings", len(accounts["accounts"]) >= 2, accounts["accounts"])
    check("no Nessie IDs in the answer", "_id" not in json.dumps(accounts))
    say("What bills do I have coming up?")
    bills = tool("get_bills")
    check("names each bill with amount and due date", bills["bills"] and "due" in bills["say"], bills["say"])
    say("Which of those come every month?")
    check("recurring filter answers", tool("get_bills", recurring=True)["ok"])
    say("How much do I still owe on my car?")
    loans = tool("get_loans")
    check("loan says what is still owed", "still owed" in loans["say"] or not loans["loans"], loans["say"])

    scene(2, "Where did my money go?")
    say("What have I bought lately?")
    purchases = tool("get_recent_purchases", limit=5)
    check("reads the purchases themselves, with amounts and dates", " on " in purchases["say"], purchases["say"])
    store = purchases["purchases"][0]["description"] if purchases["purchases"] else "CVS"
    say(f"How much have I spent at {store}?")
    by_store = tool("get_recent_purchases", merchant_name=store)
    check("filters purchases by store", all(store.lower() in p["description"].lower() for p in by_store["purchases"]))
    say(f"Where is {store}?")
    check("looks up one store, never the whole list", len(tool("find_merchant", name=store)["merchants"]) <= 5)
    say("Did my Social Security come in?")
    check("deposits answer", tool("get_deposits", limit=5)["ok"])
    say("And what has come out of savings?")
    check("withdrawals for one account", tool("get_withdrawals", account_name="savings")["ok"])
    say("Who have I sent money to?")
    check("transfers answer, even for an account with none", tool("get_transfers")["ok"])

    scene(3, "Paying part of a bill, by tapping Yes")
    before = balances()
    checking = next(name for name in before if "check" in name.lower())
    bill = (tool("get_bills")["bills"] or [None])[0]
    if bill:
        payee, owed = bill["biller_name"], float(bill["amount"])
        part = round(min(40.0, owed / 2), 2)
        say(f"Can I pay just ${part:.2f} of my {payee} bill?")
        partial = tool("pay_bill", biller_name=payee, amount=part)
        check("asks before paying, and says the rest stays due", "rest stays due" in partial["say"], partial["say"])
        current = screen()
        check("screen shows Yes / No for it", current and current["status"] == "awaiting_yes")
        check("Yes on the screen sends it", tap("Yes", partial).get("status") == "executed")
        left = next((b for b in tool("get_bills")["bills"] if b["biller_name"] == payee), None)
        check("the rest stays due", left and abs(float(left["amount"]) - (owed - part)) < 0.01, left)
        say(f"Actually, pay ${owed + 100:.2f} on it.")
        too_much = tool("pay_bill", biller_name=payee, amount=owed + 100)
        check("never more than is owed", not too_much["ok"] and "No money was moved" in too_much["say"])
        after = balances()
        check("checking went down by the payment", abs(before[checking] - after[checking] - part) < 0.01,
              (before[checking], after[checking]))
    else:
        print("    (no bills due; skipping)")

    scene(4, "A loan payment and a move from savings, by voice")
    if tool("get_loans")["loans"]:
        say("I'd like to make my car payment.")
        loan = tool("pay_loan", loan_name="car")
        say("Yes, go ahead.")
        done = tool("confirm_payment", transfer_id=loan["transfer"]["transfer_id"])
        check("voice yes pays the loan", done["ok"] and "paid toward" in done["say"], done["say"])
    before = balances()
    savings = next(name for name in before if "sav" in name.lower())
    say("Move $100 from my savings into checking.")
    move = tool("transfer_between_accounts", from_account="savings", to_account="checking", amount=100)
    check("her own account is not a new payee", "haven't sent money to before" not in move["say"])
    say("Yes please.")
    moved = tool("confirm_payment", transfer_id=move["transfer"]["transfer_id"])
    check("money moves between her accounts", moved["ok"], moved["say"])
    after = balances()
    check("savings down $100, checking up $100",
          abs(before[savings] - after[savings] - 100) < 0.01 and abs(after[checking] - before[checking] - 100) < 0.01,
          (before, after))

    scene(5, "Changing her mind")
    say("Take out $60 in cash.")
    cash = tool("withdraw", amount=60)
    check("No on the screen cancels it", tap("No", cash).get("status") == "cancelled")
    say("Send Ana $50.")
    first = tool("request_transfer", payee_name="Ana", amount=50)
    say("No wait, make it $75.")
    second = tool("request_transfer", payee_name="Ana", amount=75)
    stale = tool("confirm_payment", transfer_id=first["transfer"]["transfer_id"])
    check("the older request can no longer be sent", not stale["ok"])
    say("Yes, $75.")
    check("only the newest one goes", tool("confirm_payment", transfer_id=second["transfer"]["transfer_id"])["ok"])
    say("I have a $25 birthday check to deposit.")
    deposit = tool("deposit", amount=25, memo="Birthday check")
    check("deposit waits for a yes, then goes in", tap("Yes", deposit).get("status") == "executed")

    scene(6, "Opening an account")
    say("Can I open a savings account for my trip? Call it Travel.")
    opened = tool("create_account", account_type="Savings", nickname="Travel")
    check("it asks first, and starts at $0", "$0.00" in opened["say"])
    say("Yes.")
    check("account opens", tool("confirm_payment", transfer_id=opened["transfer"]["transfer_id"])["ok"])
    check("it shows up with $0", balances().get("Travel") == 0.0)

    scene(7, "Mistakes handled kindly")
    say("Send $20 to Zed.")
    check("unknown person: no money moved", "No money was moved" in tool("request_transfer", payee_name="Zed", amount=20)["say"])
    say("Move $10 from checking to checking.")
    check("same account is caught", not tool("transfer_between_accounts", from_account="checking",
                                              to_account="my checking account", amount=10)["ok"])
    check("fractions of a cent are refused", not tool("withdraw", amount=10.005)["ok"])
    check("an account she doesn't have is named plainly", not tool("get_deposits", account_name="brokerage")["ok"])

    scene(8, "Scam: a grandson needs bail")
    say("My grandson called. He's in jail and needs bail money right now. Please send $1,500 to Bob.")
    scam = tool("request_transfer", payee_name="Bob", amount=1500)
    check("stopped for good, with no PIN way out",
          scam["transfer"]["status"] == "held" and "PIN" not in scam["say"], scam["say"])
    check("screen shows the scam box", screen()["status"] == "held")
    check("tapping Yes can't send it", "error" in tap("Yes", scam))
    say("Fine, just send him $10 then.")
    check("anything to that person stays stopped", tool("request_transfer", payee_name="Bob", amount=10)["transfer"]["status"] == "held")

    scene(9, "Scam: open a new safe account")
    say("Someone from the fraud department says I should open a new safe account and move my money into it.")
    safe = tool("create_account", account_type="Savings", nickname="Safe")
    check("the account isn't opened", safe["transfer"]["status"] == "held", safe["say"])

    scene(10, "Scam words after the request are caught at the yes")
    say("Send Ana $400.")
    late = tool("request_transfer", payee_name="Ana", amount=400)
    check("looks normal at first", late["transfer"]["status"] == "awaiting_yes", late["say"])
    say("Yes. The IRS said there's a warrant, so do it right now.")
    stopped = tool("confirm_payment", transfer_id=late["transfer"]["transfer_id"])
    check("the second look stops it before money moves", not stopped["ok"] and "stopped" in stopped["say"], stopped["say"])


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=BASE, help="backend base URL (default %(default)s)")
    parser.add_argument("--live", action="store_true", help="allow a non-local server; this moves real Nessie money")
    options = parser.parse_args()
    BASE = options.url.rstrip("/")
    if not any(host in BASE for host in ("localhost", "127.0.0.1")) and not options.live:
        print(f"{BASE} isn't local. This script moves money; pass --live if you mean it.")
        return 2
    run()
    print(f"\n{results['pass']} passed, {results['fail']} failed")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
