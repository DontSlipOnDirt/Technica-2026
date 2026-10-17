# demo_bank.py
# A pretend Nessie that lives in memory, for testing the agent without a working Nessie key.
# Turn it on with DEMO_MODE=true. Data mirrors the team's seed: Rose pays Ana, shops at
# Fresh Market / CVS / Corner Cafe, and has a Pepco bill due. "Bob" is a stranger for the scam demo.

from datetime import date, timedelta
from typing import Any, Optional

from bank import DemoConfig
from models import TrustedContact

ROSE = "demo-rose-checking"

DEMO_CONFIG = DemoConfig(
    account_id=ROSE,
    account_name="Checking",
    payees={"ana": "demo-ana-checking", "bob": "demo-stranger"},
    trusted_contact=TrustedContact(name="Ana (daughter)", phone="555-0100"),
)


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


class DemoNessie:
    """Answers the few Nessie routes the bank uses, and remembers payments made during the demo."""

    def __init__(self):
        self.balance = 3400.0
        self.transfers = [
            {"payer_id": ROSE, "payee_id": "demo-ana-checking", "amount": 50, "transaction_date": _days_ago(45)},
            {"payer_id": ROSE, "payee_id": "demo-ana-checking", "amount": 50, "transaction_date": _days_ago(15)},
        ]
        self.bills = [{"_id": "demo-bill-pepco", "payee": "Pepco", "payment_amount": 85.0,
                       "payment_date": (date.today() + timedelta(days=7)).isoformat(), "status": "pending"}]
        self.purchases = [
            {"description": "Fresh Market", "amount": 54.20, "purchase_date": _days_ago(1)},
            {"description": "CVS Pharmacy", "amount": 18.75, "purchase_date": _days_ago(2)},
            {"description": "Corner Cafe", "amount": 9.50, "purchase_date": _days_ago(4)},
            {"description": "Fresh Market", "amount": 71.10, "purchase_date": _days_ago(8)},
            {"description": "CVS Pharmacy", "amount": 31.00, "purchase_date": _days_ago(12)},
        ]

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        routes = {
            f"/accounts/{ROSE}": {"_id": ROSE, "type": "Checking", "nickname": "Rose checking", "balance": self.balance},
            f"/accounts/{ROSE}/transfers": self.transfers,
            f"/accounts/{ROSE}/bills": self.bills,
            f"/accounts/{ROSE}/purchases": self.purchases,
        }
        if path not in routes:
            from nessie import NessieApiError
            raise NessieApiError("Not found in demo data", 404)
        return routes[path]

    def post(self, path: str, body: Any) -> Any:
        self.balance -= float(body["amount"])
        self.transfers.append({"payer_id": ROSE, **body})
        return {"code": 201}

    def put(self, path: str, body: Any) -> Any:
        for bill in self.bills:
            if path == f"/bills/{bill['_id']}":
                bill.update(body)
                self.balance -= float(bill["payment_amount"])
        return {"code": 202}
