# demo_bank.py
# A pretend Nessie that lives in memory, for testing the agent without a working Nessie key.
# Turn it on with DEMO_MODE=true. Data mirrors the team's seed: Rose pays Ana, shops at
# Fresh Market / CVS / Corner Cafe, and has a Pepco bill due. She also has savings and a car
# loan. "Bob" is a stranger for the scam demo.

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from bank import DemoConfig
from models import TrustedContact
from nessie import NessieApiError

CUSTOMER = "demo-rose"
ROSE = "demo-rose-checking"
ROSE_SAVINGS = "demo-rose-savings"
RECORDS = ("transfers", "bills", "purchases", "deposits", "withdrawals", "loans")

DEMO_CONFIG = DemoConfig(
    account_id=ROSE,
    account_name="Checking",
    payees={"ana": "demo-ana-checking", "bob": "demo-stranger"},
    trusted_contact=TrustedContact(name="Ana (daughter)", phone="555-0100"),
)


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _merchant(merchant_id: str, name: str, category: str, number: str, street: str) -> Dict[str, Any]:
    return {"_id": merchant_id, "name": name, "category": [category],
            "address": {"street_number": number, "street_name": street, "city": "College Park",
                        "state": "MD", "zip": "20740"}}


class DemoNessie:
    """Answers the Nessie routes the bank uses, and remembers what happens during the demo."""

    def __init__(self):
        self.accounts: List[Dict[str, Any]] = [
            {"_id": ROSE, "type": "Checking", "nickname": "Rose checking", "balance": 3400.0,
             "customer_id": CUSTOMER},
            {"_id": ROSE_SAVINGS, "type": "Savings", "nickname": "Rose savings", "balance": 12500.0,
             "customer_id": CUSTOMER},
        ]
        self.records: Dict[str, Dict[str, list]] = {a["_id"]: {r: [] for r in RECORDS} for a in self.accounts}
        self.records[ROSE].update({
            "transfers": [
                {"payer_id": ROSE, "payee_id": "demo-ana-checking", "amount": 50, "transaction_date": _days_ago(45)},
                {"payer_id": ROSE, "payee_id": "demo-ana-checking", "amount": 50, "transaction_date": _days_ago(15)},
            ],
            "bills": [{"_id": "demo-bill-pepco", "payee": "Pepco", "payment_amount": 85.0, "recurring_date": 1,
                       "payment_date": (date.today() + timedelta(days=7)).isoformat(), "status": "pending"}],
            "purchases": [
                {"merchant_id": "demo-fresh", "description": "Fresh Market", "amount": 54.20, "purchase_date": _days_ago(1)},
                {"merchant_id": "demo-cvs", "description": "CVS Pharmacy", "amount": 18.75, "purchase_date": _days_ago(2)},
                {"merchant_id": "demo-cafe", "description": "Corner Cafe", "amount": 9.50, "purchase_date": _days_ago(4)},
                {"merchant_id": "demo-fresh", "description": "Fresh Market", "amount": 71.10, "purchase_date": _days_ago(8)},
                {"merchant_id": "demo-cvs", "description": "CVS Pharmacy", "amount": 31.00, "purchase_date": _days_ago(12)},
            ],
            "deposits": [{"medium": "balance", "amount": 1450.0, "transaction_date": _days_ago(3),
                          "description": "Social Security", "status": "completed"}],
            "loans": [{"_id": "demo-loan-auto", "type": "auto", "status": "approved", "amount": 4200.0,
                       "monthly_payment": 350.0, "description": "Honda Civic"}],
        })
        self.merchants = {m["_id"]: m for m in (
            _merchant("demo-fresh", "Fresh Market", "Grocery", "4500", "Knox Rd"),
            _merchant("demo-cvs", "CVS Pharmacy", "Pharmacy", "7300", "Baltimore Ave"),
            _merchant("demo-cafe", "Corner Cafe", "Restaurant", "7", "Knox Rd"),
        )}

    def _account(self, account_id: str) -> Dict[str, Any]:
        for account in self.accounts:
            if account["_id"] == account_id:
                return account
        raise NessieApiError("Not found in demo data", 404)

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        parts = path.strip("/").split("/")
        if parts == ["customers", CUSTOMER, "accounts"]:
            return [dict(a) for a in self.accounts]
        if parts[0] == "accounts" and len(parts) == 2:
            return dict(self._account(parts[1]))
        if parts[0] == "accounts" and len(parts) == 3 and parts[2] in self.records.get(parts[1], {}):
            return self.records[parts[1]][parts[2]]
        if parts[0] == "merchants" and len(parts) == 2 and parts[1] in self.merchants:
            return self.merchants[parts[1]]
        raise NessieApiError("Not found in demo data", 404)

    def post(self, path: str, body: Any) -> Any:
        parts = path.strip("/").split("/")
        if parts == ["customers", CUSTOMER, "accounts"]:
            account = {"_id": f"demo-new-{len(self.accounts)}", "customer_id": CUSTOMER, **body}
            self.accounts.append(account)
            self.records[account["_id"]] = {r: [] for r in RECORDS}
            return {"code": 201, "objectCreated": account}
        account, what = self._account(parts[1]), parts[2]
        amount = float(body["amount"])
        account["balance"] += amount if what == "deposits" else -amount
        self.records[account["_id"]][what].append({"payer_id": account["_id"], **body} if what == "transfers" else dict(body))
        return {"code": 201}

    def put(self, path: str, body: Any) -> Any:
        what, record_id = path.strip("/").split("/")   # "/bills/<id>" or "/loans/<id>"
        for records in self.records.values():
            for record in records.get(what, []):
                if record.get("_id") == record_id:
                    record.update(body)
        return {"code": 202}
