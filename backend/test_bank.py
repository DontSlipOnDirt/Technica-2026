import json
import threading
import time

import pytest

import bank as bank_module
import fraud_check
from bank import Bank, BankError, DemoConfig, PaymentUnknown
from gemini_signals import GeminiUnavailable
from nessie import NessieApiError

ACCOUNT = "acct-rose"
SAVINGS = "acct-rose-savings"
CONFIG = DemoConfig(
    account_id=ACCOUNT,
    account_name="Checking",
    payees={"maria": "acct-maria", "bob": "acct-stranger"},
    today="2026-10-17",
)


class FakeNessie:
    """In-memory stand-in for the Nessie routes the bank uses."""

    def __init__(self, balance=3000.0, fail_posts=False, fail_puts=False):
        self.balance = balance
        self.fail_posts = fail_posts
        self.fail_puts = fail_puts
        self.transfers = [
            {"payer_id": ACCOUNT, "payee_id": "acct-maria", "amount": 100, "transaction_date": "2026-10-01"},
        ]
        self.bills = [{"_id": "bill-1", "payee": "Pepco", "payment_amount": 600, "status": "pending"}]
        self.purchases = [{"merchant_id": "m1", "amount": 86.40, "purchase_date": "2026-10-15", "description": "Giant"}]
        self.loans = []
        self.deposits = []
        self.withdrawals = []
        self.savings = {"transfers": [], "bills": [], "purchases": [], "loans": [], "deposits": [], "withdrawals": []}
        self.merchants = {"m1": {"_id": "m1", "name": "Giant Food", "category": ["Grocery"],
                                 "address": {"street_number": "4500", "street_name": "Knox Rd",
                                             "city": "College Park", "state": "MD", "zip": "20740"}}}
        self.more_accounts = []
        self.fail_paths = {}   # path ending -> the NessieApiError a POST there raises
        self.posted = []
        self.puts = []

    def get(self, path, params=None):
        if path == f"/accounts/{ACCOUNT}":
            return {"_id": ACCOUNT, "balance": self.balance, "nickname": "Checking", "customer_id": "cust-rose"}
        if path == "/customers/cust-rose/accounts":
            return [{"_id": ACCOUNT, "type": "Checking", "nickname": "Checking", "balance": self.balance},
                    {"_id": SAVINGS, "type": "Savings", "nickname": "Rainy day", "balance": 9000}] + self.more_accounts
        if path.split("/")[2:3] in [[a["_id"]] for a in self.more_accounts]:
            return []   # Every list on a brand-new account is empty.
        checking = {"transfers": self.transfers, "bills": self.bills, "purchases": self.purchases,
                    "loans": self.loans, "deposits": self.deposits, "withdrawals": self.withdrawals}
        for account, records in ((ACCOUNT, checking), (SAVINGS, self.savings)):
            what = path.removeprefix(f"/accounts/{account}/")
            if what in records:
                return records[what]
        if path.removeprefix("/merchants/") in self.merchants:
            return self.merchants[path.removeprefix("/merchants/")]
        raise NessieApiError("not found", 404)

    def post(self, path, body):
        if self.fail_posts:
            raise NessieApiError("Nessie request failed with status 400", 400)   # Refused: nothing moved.
        for ending, error in self.fail_paths.items():
            if path.endswith(ending):
                raise error
        if path.endswith(("/deposits", "/withdrawals")) and "status" not in body:
            # As the real Nessie answers: "1 validation error for DepositCreate status field required".
            raise NessieApiError("Nessie request failed with status 400", 400)
        self.posted.append((path, body))
        if path == "/customers/cust-rose/accounts":
            self.more_accounts.append({"_id": "acct-new", **body})
            return {"code": 201, "objectCreated": {"_id": "acct-new", **body}}
        return {"code": 201}

    def put(self, path, body):
        if self.fail_puts:
            raise NessieApiError("Nessie request failed with status 500", 500)
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
        f"/accounts/{ACCOUNT}/withdrawals",
        {"medium": "balance", "status": "completed", "amount": 50, "transaction_date": "2026-10-17",
         "description": "Lunch [payee:acct-maria]"},
    )]


def test_no_memo_still_records_who_it_went_to():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.confirm(bank.request_transfer("Maria", 50)["transfer_id"])
    assert nessie.posted[0][1]["description"] == "Transfer to Maria [payee:acct-maria]"


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
    assert nessie.posted == [(f"/accounts/{ACCOUNT}/withdrawals", {
        "medium": "balance", "status": "completed", "amount": 600.0, "transaction_date": "2026-10-17", "description": "Bill payment: Pepco"})]
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
        "medium": "balance", "status": "completed", "amount": 40, "transaction_date": "2026-10-17", "description": "Withdrawal"})]


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
        "medium": "balance", "status": "completed", "amount": 25, "transaction_date": "2026-10-17", "description": "Birthday check"})]


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


# ---- Reading bills, loans, deposits, withdrawals, transfers, and merchants ---------

def auto_loan(**over):
    return {"_id": "loan-1", "type": "auto", "status": "approved", "amount": 4200, "monthly_payment": 350,
            "description": "Honda", **over}


def test_bills_can_be_filtered_by_recurring_paid_and_account():
    nessie = FakeNessie()
    nessie.bills = [
        {"_id": "bill-1", "payee": "Pepco", "payment_amount": 85, "payment_date": "2026-10-24",
         "recurring_date": 1, "status": "pending"},
        {"_id": "bill-2", "payee": "Dr. Lee", "payment_amount": 40, "payment_date": "2026-10-20", "status": "pending"},
        {"_id": "bill-3", "payee": "Comcast", "payment_amount": 60, "status": "completed"},
    ]
    nessie.savings["bills"] = [{"_id": "bill-4", "payee": "State Farm", "payment_amount": 120,
                                "payment_date": "2026-11-01", "status": "recurring"}]
    bank = Bank(nessie, CONFIG)
    assert [b["biller_name"] for b in bank.bills()] == ["Dr. Lee", "Pepco", "State Farm"]
    assert [b["biller_name"] for b in bank.bills(recurring=True)] == ["Pepco", "State Farm"]
    assert [b["biller_name"] for b in bank.bills(recurring=False)] == ["Dr. Lee"]
    assert [b["biller_name"] for b in bank.bills(include_paid=True)] == ["Comcast", "Dr. Lee", "Pepco", "State Farm"]
    assert [b["biller_name"] for b in bank.bills("savings")] == ["State Farm"]
    assert bank.bills()[0] == {"biller_name": "Dr. Lee", "amount": 40, "due_date": "2026-10-20",
                               "status": "pending", "recurring": False, "account": "Checking"}


def test_loans_are_named_not_numbered():
    nessie = FakeNessie()
    nessie.loans = [auto_loan()]
    assert Bank(nessie, CONFIG).loans() == [{"name": "Auto loan", "amount_owed": 4200, "monthly_payment": 350,
                                             "status": "approved", "description": "Honda", "account": "Checking"}]


def test_deposits_and_withdrawals_come_newest_first_from_every_account():
    nessie = FakeNessie()
    nessie.deposits = [{"amount": 1450, "transaction_date": "2026-10-03", "description": "Social Security",
                        "status": "completed"}]
    nessie.savings["deposits"] = [{"amount": 20, "transaction_date": "2026-10-10", "description": "Interest",
                                   "status": "completed"}]
    nessie.withdrawals = [{"amount": 60, "transaction_date": "2026-10-12", "description": "ATM [cat:Cash]",
                           "status": "completed"}]
    bank = Bank(nessie, CONFIG)
    assert [(d["account"], d["description"]) for d in bank.deposits()] == [
        ("Rainy day", "Interest"), ("Checking", "Social Security")]
    assert [d["description"] for d in bank.deposits("checking", limit=5)] == ["Social Security"]
    assert bank.withdrawals() == [{"account": "Checking", "description": "ATM", "amount": 60,
                                   "date": "2026-10-12", "status": "completed"}]


def test_transfers_name_who_sent_and_who_got_the_money():
    nessie = FakeNessie()
    nessie.transfers = [
        {"_id": "x1", "amount": 100, "transaction_date": "2026-10-01", "description": "Lunch [payee:acct-maria]"},
        {"_id": "x2", "amount": 500, "transaction_date": "2026-10-05", "description": "Saving [payee:acct-rose-savings]"},
        {"_id": "x3", "amount": 5, "transaction_date": "2026-10-06", "description": "Mystery"},
    ]
    t = Bank(nessie, CONFIG).transfers()
    assert [(x["from"], x["to"], x["amount"], x["description"]) for x in t] == [
        ("Checking", None, 5, "Mystery"), ("Checking", "Rainy day", 500, "Saving"), ("Checking", "Maria", 100, "Lunch")]


def test_purchases_can_be_filtered_by_merchant_name():
    nessie = FakeNessie()
    nessie.purchases = [
        {"merchant_id": "m1", "amount": 86.40, "purchase_date": "2026-10-15", "description": "Groceries"},
        {"merchant_id": "m2", "amount": 12.00, "purchase_date": "2026-10-16", "description": "CVS Pharmacy"},
        {"merchant_id": "gone", "amount": 3.00, "purchase_date": "2026-10-14", "description": "Parking"},
    ]
    nessie.savings["purchases"] = [{"amount": 20.0, "purchase_date": "2026-10-17", "description": "Snacks [merchant:m1]"}]
    bank = Bank(nessie, CONFIG)
    # Neither description says Giant; the merchant's name does. Merchants Nessie can't find are skipped.
    assert [(p["amount"], p["account"]) for p in bank.recent_purchases(merchant_name="giant")] == [
        (20.0, "Rainy day"), (86.40, "Checking")]
    assert [p["description"] for p in bank.recent_purchases(merchant_name="cvs")] == ["CVS Pharmacy"]
    assert bank.recent_purchases(merchant_name="Target") == []
    assert [p["amount"] for p in bank.recent_purchases(account_name="savings")] == [20.0]


def test_find_merchant_only_searches_her_own_purchases():
    nessie = FakeNessie()
    nessie.merchants["m9"] = {"_id": "m9", "name": "Giant Eagle", "category": "Grocery"}   # She never shopped there.
    bank = Bank(nessie, CONFIG)
    assert bank.find_merchant("giant") == [{"name": "Giant Food", "category": "Grocery",
                                            "address": "4500 Knox Rd, College Park, MD 20740"}]
    assert bank.find_merchant("Eagle") == []
    with pytest.raises(BankError):
        bank.find_merchant(" ")


def test_read_answers_never_include_nessie_ids():
    nessie = FakeNessie()
    nessie.loans = [auto_loan()]
    nessie.transfers.append({"_id": "x2", "amount": 500, "transaction_date": "2026-10-05",
                             "description": "Saving [payee:acct-rose-savings]"})
    bank = Bank(nessie, CONFIG)
    answers = json.dumps([bank.summary(), bank.list_accounts(), bank.recent_purchases(), bank.deposits(),
                          bank.withdrawals(), bank.transfers(), bank.bills(include_paid=True), bank.loans(),
                          bank.find_merchant("giant")])
    for nessie_id in ("acct-", "bill-1", "loan-1", "cust-rose", '"m1"', "x2"):
        assert nessie_id not in answers


# ---- Moving money between her own accounts ------------------------------------------

def test_accounts_are_found_however_she_names_them():
    bank = make_bank()
    for said in ("savings", "my savings account", "Rainy day", "rainy"):
        assert bank.transfer_between_accounts("checking", said, 10)["payee_name"] == "Rainy day"
    with pytest.raises(BankError, match="couldn't find an account called brokerage"):
        bank.transfer_between_accounts("checking", "brokerage", 10)


def test_two_accounts_that_fit_the_name_means_asking_which():
    nessie = FakeNessie()
    nessie.more_accounts.append({"_id": "acct-travel", "type": "Savings", "nickname": "Travel", "balance": 10})
    with pytest.raises(BankError, match="Rainy day or Travel"):
        Bank(nessie, CONFIG).transfer_between_accounts("checking", "savings", 10)


def test_moving_money_between_her_accounts_waits_for_a_yes_then_moves_it_once():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.transfer_between_accounts("savings", "checking", 500)
    assert (t["kind"], t["status"]) == ("own_transfer", "awaiting_yes")
    assert (t["from_account_name"], t["payee_name"]) == ("Rainy day", "Checking")
    assert t["spoken_message"] == "I'll move $500.00 from your Rainy day account to your checking account. Are you sure?"
    assert nessie.posted == []
    bank.confirm(t["transfer_id"])
    bank.confirm(t["transfer_id"])
    # This Nessie's transfers carry no payee, so the money lands in checking as a deposit.
    assert nessie.posted == [
        (f"/accounts/{SAVINGS}/withdrawals", {"medium": "balance", "status": "completed", "amount": 500, "transaction_date": "2026-10-17",
                                            "description": "Transfer to Checking [payee:acct-rose]"}),
        (f"/accounts/{ACCOUNT}/deposits", {"medium": "balance", "status": "completed", "amount": 500, "transaction_date": "2026-10-17",
                                           "description": "Transfer from Rainy day"}),
    ]


def test_moving_money_between_her_accounts_changes_both_balances_once():
    # The event's Nessie never changes balances, so the bank shows what it moved.
    bank = make_bank()
    t = bank.transfer_between_accounts("savings", "checking", 500)
    bank.confirm(t["transfer_id"])
    bank.confirm(t["transfer_id"])
    balances = {a["name"]: a["balance"] for a in bank.list_accounts()}
    assert balances == {"Checking": 3500.0, "Rainy day": 8500.0}
    assert bank.summary()["balance"] == 3500.0


def test_paying_a_bill_lowers_the_balance():
    bank = make_bank()
    bank.confirm(bank.pay_bill("pepco")["transfer_id"])
    assert bank.summary()["balance"] == 2400.0


def test_nothing_changes_a_balance_before_yes_or_when_held():
    bank = make_bank()
    bank.transfer_between_accounts("checking", "savings", 100)   # never confirmed
    bank.add_transcript_line("c1", "the fraud department says move it to a safe account right now")
    held = bank.request_transfer("Bob", 2000)
    with pytest.raises(BankError):
        bank.confirm(held["transfer_id"])
    assert {a["name"]: a["balance"] for a in bank.list_accounts()} == {"Checking": 3000.0, "Rainy day": 9000.0}


def test_a_failed_payment_changes_no_balance():
    bank = make_bank(fail_posts=True)
    t = bank.transfer_between_accounts("savings", "checking", 500)
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])
    assert bank.summary()["balance"] == 3000.0


def test_the_fraud_check_sees_the_balance_after_earlier_moves():
    # After moving most of checking out, sending the rest is "most of your balance".
    bank = make_bank()
    bank.confirm(bank.transfer_between_accounts("checking", "savings", 2500)["transfer_id"])
    t = bank.request_transfer("Maria", 300)
    assert "This is more than half of your balance" in t["reasons"]


def test_someone_she_paid_through_a_tagged_withdrawal_is_a_known_payee():
    nessie = FakeNessie()
    nessie.transfers = []
    nessie.withdrawals = [{"amount": 100, "transaction_date": "2026-10-01", "status": "completed",
                           "description": "Lunch [payee:acct-maria]"}]
    t = Bank(nessie, CONFIG).request_transfer("Maria", 50)
    assert t["risk_score"] == 0, t["reasons"]


class NoTransfersNessie(FakeNessie):
    """The real Nessie answers 404 "No transfers found for this account" instead of []."""

    def get(self, path, params=None):
        if path.endswith("/transfers") and not super().get(path, params):
            raise NessieApiError("Nessie request failed with status 404", 404)
        return super().get(path, params)


def test_an_account_with_no_transfers_yet_still_works():
    nessie = NoTransfersNessie()
    bank = Bank(nessie, CONFIG)
    assert bank.transfers("savings") == []
    t = bank.transfer_between_accounts("savings", "checking", 50)
    assert t["status"] == "awaiting_yes"
    bank.confirm(t["transfer_id"])
    assert [path for path, _ in nessie.posted] == [f"/accounts/{SAVINGS}/withdrawals", f"/accounts/{ACCOUNT}/deposits"]


def test_her_own_accounts_are_not_new_payees():
    t = make_bank().transfer_between_accounts("checking", "savings", 100)
    assert t["risk_score"] == 0, t["reasons"]


def test_a_scam_story_holds_a_move_between_accounts():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "the fraud department says my savings is not safe, move it to checking right now")
    t = bank.transfer_between_accounts("savings", "checking", 6000)
    assert t["status"] == "held"
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])
    assert nessie.posted == []


def test_moving_to_the_same_account_is_an_error():
    with pytest.raises(BankError, match="same account"):
        make_bank().transfer_between_accounts("checking", "my checking account", 10)


def test_amounts_are_dollars_and_cents():
    with pytest.raises(BankError, match="dollars and cents"):
        make_bank().request_transfer("Maria", 10.005)


# ---- Bills: in full, in part, never more than owed -------------------------------

def test_part_of_a_bill_can_be_paid_and_the_rest_stays_due():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.pay_bill("Pepco", 200)
    assert (t["amount"], t["amount_owed"]) == (200, 600)
    assert t["spoken_message"] == ("I'll pay $200.00 of your $600.00 Pepco bill from your checking account. "
                                   "The rest stays due. Are you sure?")
    bank.confirm(t["transfer_id"])
    assert nessie.posted == [(f"/accounts/{ACCOUNT}/withdrawals", {
        "medium": "balance", "status": "completed", "amount": 200, "transaction_date": "2026-10-17", "description": "Bill payment: Pepco"})]
    assert nessie.puts == [("/bills/bill-1", {"payment_amount": 400})]


def test_a_bill_can_never_be_overpaid():
    bank = make_bank()
    with pytest.raises(BankError, match=r"more than the \$600.00 you owe Pepco"):
        bank.pay_bill("Pepco", 600.01)
    assert bank.current() is None


def test_a_bill_can_be_paid_from_savings():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.pay_bill("Pepco", from_account="savings")
    assert t["from_account_name"] == "Rainy day"
    bank.confirm(t["transfer_id"])
    assert nessie.posted[0][0] == f"/accounts/{SAVINGS}/withdrawals"


def test_a_bill_on_her_savings_is_a_known_payee():
    nessie = FakeNessie()
    nessie.bills = []
    nessie.savings["bills"] = [{"_id": "bill-9", "payee": "State Farm", "payment_amount": 120, "status": "pending"}]
    t = Bank(nessie, CONFIG).pay_bill("state farm")
    assert t["risk_score"] == 0, t["reasons"]


# ---- Loans --------------------------------------------------------------------------

def test_loan_payment_waits_for_a_yes_then_lowers_what_is_owed():
    nessie = FakeNessie()
    nessie.loans = [auto_loan()]
    bank = Bank(nessie, CONFIG)
    t = bank.pay_loan("my car loan")
    assert (t["kind"], t["payee_name"], t["amount"], t["status"]) == ("loan", "Auto loan", 350, "awaiting_yes")
    assert "This is someone you haven't sent money to before" not in t["reasons"]
    assert t["spoken_message"].endswith("I'll pay $350.00 toward your auto loan from your checking account. Are you sure?")
    assert nessie.posted == []
    bank.confirm(t["transfer_id"])
    assert nessie.posted == [(f"/accounts/{ACCOUNT}/withdrawals", {
        "medium": "balance", "status": "completed", "amount": 350, "transaction_date": "2026-10-17", "description": "Loan payment: Auto loan"})]
    assert nessie.puts == [("/loans/loan-1", {"amount": 3850})]


def test_a_loan_can_never_be_overpaid_and_the_last_payment_is_what_is_left():
    nessie = FakeNessie()
    nessie.loans = [auto_loan(amount=120)]
    bank = Bank(nessie, CONFIG)
    with pytest.raises(BankError, match=r"more than the \$120.00 still owed on your auto loan"):
        bank.pay_loan("auto", 500)
    assert bank.pay_loan()["amount"] == 120


def test_paying_a_loan_needs_one_she_has():
    nessie = FakeNessie()
    with pytest.raises(BankError, match="don't see any loans"):
        Bank(nessie, CONFIG).pay_loan("auto")
    nessie.loans = [auto_loan(), auto_loan(_id="loan-2", type="home", description="Maple St")]
    bank = Bank(nessie, CONFIG)
    with pytest.raises(BankError, match="Auto loan or Home loan"):
        bank.pay_loan()
    assert bank.pay_loan("mortgage", 100)["payee_name"] == "Home loan"


def test_a_failed_record_update_after_the_money_moved_never_sends_twice():
    nessie = FakeNessie(fail_puts=True)
    nessie.loans = [auto_loan()]
    bank = Bank(nessie, CONFIG)
    t = bank.pay_loan("auto")
    assert bank.confirm(t["transfer_id"])["status"] == "executed"
    assert bank.confirm(t["transfer_id"])["status"] == "executed"
    assert len(nessie.posted) == 1


# ---- Opening an account -------------------------------------------------------------

def test_opening_an_account_waits_for_a_yes_and_starts_at_zero():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    t = bank.create_account("savings account", "Travel")
    assert (t["kind"], t["status"], t["amount"], t["account_type"], t["payee_name"]) == (
        "new_account", "awaiting_yes", 0, "Savings", "Travel")
    assert t["spoken_message"] == "I'll open a new savings account called Travel, with a $0.00 balance. Are you sure?"
    assert nessie.posted == []
    bank.confirm(t["transfer_id"])
    assert nessie.posted == [("/customers/cust-rose/accounts",
                              {"type": "Savings", "nickname": "Travel", "rewards": 0, "balance": 0})]


def test_without_a_nickname_the_account_is_named_for_its_type():
    t = make_bank().create_account("Checking")
    assert t["payee_name"] == "Checking"
    assert t["spoken_message"] == "I'll open a new checking account, with a $0.00 balance. Are you sure?"


def test_any_scam_sign_stops_opening_an_account():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "a man from the fraud department said to open a new savings account")
    t = bank.create_account("savings")
    # For a payment this score would only be a careful confirm; opening an account stops.
    assert t["risk_score"] < fraud_check.HOLD_AT
    assert (t["status"], t["decision"]) == ("held", "hold")
    assert t["spoken_message"].startswith("I haven't opened this account, to keep your money safe.")
    assert "PIN" not in t["spoken_message"]
    with pytest.raises(BankError):
        bank.confirm(t["transfer_id"])
    assert nessie.posted == []


def test_only_three_kinds_of_account_can_be_opened():
    with pytest.raises(BankError, match="checking, savings, or credit card"):
        make_bank().create_account("brokerage")


def test_an_account_opened_here_is_still_a_new_payee():
    # "Open a new account, then move your money into it" is the safe-account scam.
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.confirm(bank.create_account("savings", "Travel")["transfer_id"])
    new = "This is someone you haven't sent money to before"
    assert new in bank.transfer_between_accounts("checking", "travel", 100)["reasons"]
    assert new not in bank.transfer_between_accounts("checking", "rainy day", 100)["reasons"]


# ---- Her words reach the scam check before money moves ------------------------------

SCAM_WORDS = "the fraud department says move it to a safe account right now"


def test_a_payment_waits_for_the_words_that_asked_for_it(monkeypatch):
    # The agent's tool call can beat the screen's post of what she just said.
    monkeypatch.setattr(bank_module, "WORDS_FRESH_S", 0.0)   # Every earlier line counts as old.
    bank = make_bank()
    bank.add_transcript_line("c1", "hello")
    late = threading.Timer(0.2, bank.add_transcript_line, ("c1", SCAM_WORDS))
    late.start()
    t = bank.request_transfer("Bob", 900)
    late.join()
    assert t["status"] == "held"


def test_with_no_new_words_a_payment_goes_ahead_after_a_short_wait(monkeypatch):
    monkeypatch.setattr(bank_module, "WORDS_FRESH_S", 0.0)
    monkeypatch.setattr(bank_module, "WORDS_WAIT_S", 0.05)
    bank = make_bank()
    bank.add_transcript_line("c1", "send fifty dollars to Maria")
    assert bank.request_transfer("Maria", 50)["status"] == "awaiting_yes"


def test_fresh_words_or_no_screen_means_no_wait(monkeypatch):
    monkeypatch.setattr(bank_module, "WORDS_WAIT_S", 30)
    start = time.monotonic()
    make_bank().request_transfer("Maria", 50)          # No screen has sent anything.
    bank = make_bank()
    bank.add_transcript_line("c1", "send fifty dollars to Maria")
    bank.request_transfer("Maria", 50)                 # Her words just arrived.
    assert time.monotonic() - start < 5


def test_scam_words_after_the_request_stop_it_at_the_yes():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "send nine hundred dollars to Bob")
    t = bank.request_transfer("Bob", 900)
    assert t["status"] == "awaiting_yes"
    bank.add_transcript_line("c1", "yes, the fraud department told me to hurry")
    with pytest.raises(BankError, match="I've stopped this payment to keep your money safe"):
        bank.confirm(t["transfer_id"])
    assert (bank.current()["status"], bank.current()["decision"]) == ("held", "hold")
    assert nessie.posted == []
    assert bank.request_transfer("Bob", 5)["status"] == "held"


def test_a_plain_yes_still_sends():
    nessie = FakeNessie()
    bank = Bank(nessie, CONFIG)
    bank.add_transcript_line("c1", "send fifty dollars to Maria")
    t = bank.request_transfer("Maria", 50)
    bank.add_transcript_line("c1", "yes please")
    assert bank.confirm(t["transfer_id"])["status"] == "executed"


# ---- When nobody knows whether the money moved --------------------------------------

def test_a_timeout_on_the_yes_is_unknown_and_never_retried():
    nessie = FakeNessie()
    nessie.fail_paths["/withdrawals"] = NessieApiError("Nessie request timed out", 408, outcome_unknown=True)
    bank = Bank(nessie, CONFIG)
    t = bank.request_transfer("Maria", 50)
    with pytest.raises(PaymentUnknown, match="not sure that payment went through"):
        bank.confirm(t["transfer_id"])
    assert bank.current()["status"] == "unknown"
    nessie.fail_paths.clear()
    with pytest.raises(PaymentUnknown):
        bank.confirm(t["transfer_id"])   # It may have gone through: never send it a second time.
    with pytest.raises(PaymentUnknown):
        bank.cancel(t["transfer_id"])
    assert nessie.posted == []


def test_a_refused_payment_is_known_not_to_have_moved():
    nessie = FakeNessie()
    nessie.fail_paths["/withdrawals"] = NessieApiError("Nessie request failed with status 400", 400)
    bank = Bank(nessie, CONFIG)
    t = bank.withdraw(40)
    with pytest.raises(BankError) as err:
        bank.confirm(t["transfer_id"])
    assert not isinstance(err.value, PaymentUnknown)
    assert bank.current()["status"] == "awaiting_yes"


def test_money_that_left_but_did_not_arrive_is_reported_honestly():
    nessie = FakeNessie()
    nessie.fail_paths["/deposits"] = NessieApiError("Nessie request failed with status 400", 400)
    bank = Bank(nessie, CONFIG)
    t = bank.transfer_between_accounts("checking", "savings", 100)
    with pytest.raises(PaymentUnknown, match="left your checking account, but I couldn't confirm it reached"):
        bank.confirm(t["transfer_id"])
    assert bank.current()["status"] == "unknown"
    assert [path for path, _ in nessie.posted] == [f"/accounts/{ACCOUNT}/withdrawals"]
