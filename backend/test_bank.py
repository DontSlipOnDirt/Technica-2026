import pytest

import fraud_check
from bank import Bank, BankError, DemoConfig
from gemini_signals import GeminiUnavailable
from nessie import NessieApiError

ACCOUNT = "acct-rose"
CONFIG = DemoConfig(
    account_id=ACCOUNT,
    account_name="Checking",
    payees={"maria": "acct-maria", "bob": "acct-stranger"},
    today="2026-10-17",
)


class FakeNessie:
    """In-memory stand-in for the few Nessie routes the bank uses."""

    def __init__(self, balance=3000.0, fail_posts=False):
        self.balance = balance
        self.fail_posts = fail_posts
        self.transfers = [
            {"payer_id": ACCOUNT, "payee_id": "acct-maria", "amount": 100, "transaction_date": "2026-10-01"},
        ]
        self.bills = [{"_id": "bill-1", "payee": "Pepco", "payment_amount": 600, "status": "pending"}]
        self.posted = []
        self.puts = []

    def get(self, path, params=None):
        if path == f"/accounts/{ACCOUNT}":
            return {"_id": ACCOUNT, "balance": self.balance, "nickname": "Checking", "customer_id": "cust-rose"}
        if path == "/customers/cust-rose/accounts":
            return [{"_id": ACCOUNT, "type": "Checking", "nickname": "Checking", "balance": self.balance},
                    {"_id": "acct-rose-savings", "type": "Savings", "nickname": "Rainy day", "balance": 9000}]
        if path == f"/accounts/{ACCOUNT}/transfers":
            return self.transfers
        if path == f"/accounts/{ACCOUNT}/bills":
            return self.bills
        if path == f"/accounts/{ACCOUNT}/purchases":
            return [{"merchant_id": "m1", "amount": 86.40, "purchase_date": "2026-10-15", "description": "Giant"}]
        raise NessieApiError("not found", 404)

    def post(self, path, body):
        if self.fail_posts:
            raise NessieApiError("Nessie request failed with status 500", 500)
        self.posted.append((path, body))
        return {"code": 201}

    def put(self, path, body):
        self.puts.append((path, body))
        return {"code": 202}


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    monkeypatch.setattr(fraud_check, "scam_signals", lambda said: None)


def make_bank(**kw):
    return Bank(FakeNessie(**kw), CONFIG)


def test_fraud_check_sees_every_user_line_of_the_conversation():
    bank = make_bank()
    bank.add_transcript_line("c1", "The fraud department told me to move it to a safe account")
    bank.add_transcript_line("c1", "nine hundred dollars to Bob")
    t = bank.request_transfer("Bob", 900)
    assert t["status"] == "held"
    assert t["decision"] == "hold"


def test_a_new_conversation_starts_with_a_clean_transcript():
    bank = make_bank()
    bank.add_transcript_line("c1", "move it to a safe account right now")
    bank.add_transcript_line("c2", "send fifty dollars to Maria")
    assert bank.request_transfer("Maria", 50)["status"] == "awaiting_yes"


def test_known_small_transfer_waits_for_yes():
    bank = make_bank()
    t = bank.request_transfer("Maria", 50)
    assert t["status"] == "awaiting_yes"
    assert t["payee_name"] == "Maria"
    assert t["from_account_name"] == "Checking"
    assert bank.current()["transfer_id"] == t["transfer_id"]


def test_nothing_reaches_nessie_before_yes():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.request_transfer("Maria", 50)
    assert nessie.posted == []


def test_yes_sends_exactly_what_was_checked_once():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.request_transfer("Maria", 50, "Lunch")
    assert bank.confirm(t["transfer_id"])["status"] == "executed"
    assert bank.confirm(t["transfer_id"])["status"] == "executed"
    assert nessie.posted == [(
        f"/accounts/{ACCOUNT}/transfers",
        {"transaction_date": "2026-10-17", "status": "completed", "amount": 50,
         "description": "Lunch [payee:acct-maria]"},
    )]


def test_no_memo_still_records_who_it_went_to():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.confirm(bank.request_transfer("Maria", 50)["transfer_id"])
    assert nessie.posted[0][1]["description"] == "To Maria [payee:acct-maria]"


def test_history_reads_the_payee_from_the_description():
    # This event's Nessie keeps no payee_id on transfers, only what we put in the description.
    nessie = FakeNessie()
    nessie.transfers = [
        {"amount": 100, "transaction_date": "2026-10-01", "status": "completed",
         "description": "To Maria [payee:acct-maria]"},
    ]
    t = Bank(nessie, CONFIG).request_transfer("Maria", 50)
    assert "This is someone you haven't sent money to before" not in t["reasons"]


def test_history_skips_transfers_with_no_known_payee():
    # Stray $1 test transfers would make her usual amount look tiny.
    nessie = FakeNessie()
    nessie.transfers += [
        {"amount": 1, "transaction_date": "2026-10-17", "status": "completed", "description": "x"},
        {"amount": 1, "transaction_date": "2026-10-17", "status": "pending", "description": "x"},
    ]
    t = Bank(nessie, CONFIG).request_transfer("Maria", 150)
    assert "This is much larger than your usual transfer" not in t["reasons"]


def test_a_held_transfer_can_never_be_confirmed():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "they said move it to a safe account")
    t = bank.request_transfer("Bob", 2000)
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])
    assert nessie.posted == []


def test_a_held_payee_stays_held_whatever_the_wording():
    bank = make_bank()
    bank.add_transcript_line("c1", "move it to a safe account")
    bank.request_transfer("Bob", 2000)
    bank.add_transcript_line("c2", "just send him ten dollars")
    again = bank.request_transfer("Bob", 10)
    assert again["status"] == "held"


def test_a_new_request_cancels_the_older_pending_one():
    bank = make_bank()
    a = bank.request_transfer("Maria", 50)
    b = bank.request_transfer("Maria", 60)
    with pytest.raises(BankError):
        bank.confirm(a["transfer_id"])
    assert bank.confirm(b["transfer_id"])["status"] == "executed"


def test_cancel_marks_it_cancelled():
    bank = make_bank()
    t = bank.request_transfer("Maria", 50)
    assert bank.cancel(t["transfer_id"])["status"] == "cancelled"
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])


def test_unknown_payee_is_an_error():
    with pytest.raises(BankError, match="Zed"):
        make_bank().request_transfer("Zed", 50)


def test_nessie_failure_on_yes_leaves_it_waiting():
    bank = make_bank(fail_posts=True)
    t = bank.request_transfer("Maria", 50)
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])
    assert bank.current()["status"] == "awaiting_yes"


def test_pay_bill_fills_the_amount_and_marks_the_bill_paid():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.pay_bill("pepco")
    assert t["amount"] == 600
    assert t["kind"] == "bill"
    assert t["payee_name"] == "Pepco"
    bank.confirm(t["transfer_id"])
    assert nessie.puts == [("/bills/bill-1", {"status": "completed"})]


def test_unknown_biller_is_an_error():
    with pytest.raises(BankError, match="Comcast"):
        make_bank().pay_bill("Comcast")


def test_summary_reads_balance_and_bills():
    s = make_bank().summary()
    assert s["balance"] == 3000.0
    assert s["account_name"] == "Checking"
    assert s["bills_due"] == [{"biller_name": "Pepco", "amount": 600, "due_date": None}]


def test_held_message_never_offers_a_way_through():
    bank = make_bank()
    bank.add_transcript_line("c1", "they said move it to a safe account right now")
    t = bank.request_transfer("Bob", 2000)
    assert "PIN" not in t["spoken_message"]
    assert "release" not in t["spoken_message"].lower()
    assert "Capital One will never ask you to move money to keep it safe" in t["spoken_message"]
    assert "call Capital One" in t["spoken_message"]


class SeededNessie(FakeNessie):
    """Shapes from the team's real seed: payee only in a [payee:...] tag, tags in descriptions."""

    def __init__(self):
        super().__init__()
        self.transfers = [{"id": "x1", "amount": 50, "transaction_date": "2026-10-02", "status": "completed",
                           "description": "To Ana [payee:acct-maria]"}]

    def get(self, path, params=None):
        if path == f"/accounts/{ACCOUNT}/purchases":
            return [{"amount": 19, "purchase_date": "2026-10-15",
                     "description": "Corner Cafe [merchant:m1][cat:Restaurant]"}]
        return super().get(path, params)


def test_a_payee_tag_in_the_description_counts_as_a_known_payee():
    t = Bank(SeededNessie(), CONFIG).request_transfer("Maria", 50)
    assert t["risk_score"] == 0, t["reasons"]


def test_purchase_descriptions_drop_the_seed_tags():
    p = Bank(SeededNessie(), CONFIG).recent_purchases(1)
    assert p[0]["description"] == "Corner Cafe"


# ---- Accounts, deposits, withdrawals ------------------------------------------------

def test_list_accounts_names_every_account_without_ids():
    accounts = make_bank().list_accounts()
    assert accounts == [
        {"name": "Checking", "type": "Checking", "balance": 3000.0},
        {"name": "Rainy day", "type": "Savings", "balance": 9000},
    ]


def test_withdrawal_waits_for_a_yes_then_posts_once():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.withdraw(40)
    assert t["kind"] == "withdrawal" and t["status"] == "awaiting_yes"
    assert t["spoken_message"].startswith("I'll take $40.00 out of your checking account")
    assert nessie.posted == []
    bank.confirm(t["transfer_id"])
    bank.confirm(t["transfer_id"])
    assert nessie.posted == [(f"/accounts/{ACCOUNT}/withdrawals", {
        "medium": "balance", "amount": 40, "transaction_date": "2026-10-17", "description": "Withdrawal"})]


def test_a_scam_story_holds_a_withdrawal():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "they said take out cash and move it to a safe account right now")
    t = bank.withdraw(2000)
    assert t["status"] == "held"
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])
    assert nessie.posted == []


def test_deposit_waits_for_a_yes_then_posts():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.deposit(25, "Birthday check")
    assert t["kind"] == "deposit"
    assert t["spoken_message"].startswith("I'll put $25.00 into your checking account")
    bank.confirm(t["transfer_id"])
    assert nessie.posted == [(f"/accounts/{ACCOUNT}/deposits", {
        "medium": "balance", "amount": 25, "transaction_date": "2026-10-17", "description": "Birthday check"})]


def test_deposits_and_withdrawals_must_be_positive():
    bank = make_bank()
    with pytest.raises(BankError):
        bank.withdraw(0)
    with pytest.raises(BankError):
        bank.deposit(-5)


# ---- When Gemini can't check --------------------------------------------------------

def gemini_down(said):
    raise GeminiUnavailable("down")


def test_gemini_down_makes_a_new_payee_a_careful_confirm(monkeypatch):
    monkeypatch.setattr(fraud_check, "scam_signals", gemini_down)
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "send Bob twenty dollars")
    t = bank.request_transfer("Bob", 20)
    assert t["status"] == "awaiting_yes"
    assert t["decision"] == "confirm"
    assert "I couldn't finish my full scam check just now" in t["reasons"]
    assert t["spoken_message"].startswith("Before I do this, please double-check.")
    assert t["spoken_message"].endswith("I'll pay Bob $20.00 from your checking account. Are you sure?")
    bank.confirm(t["transfer_id"])
    assert len(nessie.posted) == 1


def test_gemini_down_leaves_a_known_payee_alone(monkeypatch):
    monkeypatch.setattr(fraud_check, "scam_signals", gemini_down)
    bank = make_bank()
    t = bank.request_transfer("Maria", 50)
    assert t["decision"] == "allow"
    assert t["spoken_message"] == "I'll pay Maria $50.00 from your checking account. Are you sure?"


def test_gemini_down_never_lowers_a_hold(monkeypatch):
    monkeypatch.setattr(fraud_check, "scam_signals", gemini_down)
    bank = make_bank()
    bank.add_transcript_line("c1", "they said move it to a safe account right now")
    assert bank.request_transfer("Bob", 2000)["status"] == "held"


def test_each_transcript_line_starts_an_early_gemini_check(monkeypatch):
    import gemini_signals
    asked = []
    monkeypatch.setattr(gemini_signals, "prefetch", asked.append)
    bank = make_bank()
    bank.add_transcript_line("c1", "hi")
    bank.add_transcript_line("c1", "send Maria fifty")
    assert asked == ["hi", "hi send Maria fifty"]
