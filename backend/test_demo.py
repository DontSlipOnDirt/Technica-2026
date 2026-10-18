import fraud_check
import pytest

from bank import Bank
from demo_bank import DEMO_CONFIG, DemoNessie


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    monkeypatch.setattr(fraud_check, "scam_signals", lambda said: None)


def test_demo_summary_has_rose_balance_and_pepco_bill():
    s = Bank(DemoNessie(), DEMO_CONFIG).summary()
    assert s["balance"] == 3400.0
    assert s["bills_due"][0]["biller_name"] == "Pepco"


def test_demo_purchases_are_newest_first():
    p = Bank(DemoNessie(), DEMO_CONFIG).recent_purchases(3)
    assert len(p) == 3
    assert p[0]["date"] >= p[1]["date"] >= p[2]["date"]


def test_demo_small_payment_to_ana_goes_through():
    nessie = DemoNessie()
    bank = Bank(nessie, DEMO_CONFIG)
    t = bank.request_transfer("Ana", 50)
    assert t["status"] == "awaiting_yes"
    bank.confirm(t["transfer_id"])
    assert bank.summary()["balance"] == 3350.0


def test_demo_scam_to_bob_is_held():
    bank = Bank(DemoNessie(), DEMO_CONFIG)
    bank.add_transcript_line("c1", "The fraud department said move my money to a safe account right now")
    assert bank.request_transfer("Bob", 2000)["status"] == "held"


def test_demo_bill_payment_marks_it_paid():
    bank = Bank(DemoNessie(), DEMO_CONFIG)
    t = bank.pay_bill("Pepco")
    bank.confirm(t["transfer_id"])
    assert bank.summary()["bills_due"] == []
    assert bank.summary()["balance"] == 3315.0


def test_demo_has_savings_a_car_loan_and_store_details():
    bank = Bank(DemoNessie(), DEMO_CONFIG)
    assert [a["name"] for a in bank.list_accounts()] == ["Checking", "Rose savings"]
    assert bank.loans()[0]["name"] == "Auto loan"
    assert bank.find_merchant("cvs")[0]["address"] == "7300 Baltimore Ave, College Park, MD 20740"


def test_demo_move_from_savings_lands_in_checking():
    bank = Bank(DemoNessie(), DEMO_CONFIG)
    bank.confirm(bank.transfer_between_accounts("savings", "checking", 100)["transfer_id"])
    assert {a["name"]: a["balance"] for a in bank.list_accounts()} == {"Checking": 3500.0, "Rose savings": 12400.0}


def test_demo_loan_payment_lowers_the_balance_and_what_is_owed():
    bank = Bank(DemoNessie(), DEMO_CONFIG)
    bank.confirm(bank.pay_loan("car")["transfer_id"])
    assert bank.summary()["balance"] == 3050.0
    assert bank.loans()[0]["amount_owed"] == 3850.0


def test_demo_new_account_opens_empty():
    bank = Bank(DemoNessie(), DEMO_CONFIG)
    bank.confirm(bank.create_account("savings", "Travel")["transfer_id"])
    assert {"name": "Travel", "type": "Savings", "balance": 0} in bank.list_accounts()
