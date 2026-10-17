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
