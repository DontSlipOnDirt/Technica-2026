# seed_nessie.py
# Tops up the team's demo data in Nessie so it matches demo_bank.py.
# A teammate already seeded Rose (with purchases and past $50 transfers to Ana),
# so this only adds what's missing: the Pepco bill, and Bob the stranger for the scam demo.
# Safe to run more than once: it looks before it creates.
#
#   python seed_nessie.py
# Then paste the lines it prints into .env.

import os
from datetime import date, timedelta
from pathlib import Path

from nessie import NessieClient

# The team's Rose and Ana (seeded by a teammate).
ROSE_ACCOUNT = "5e2a11be-f148-442c-803a-9bcafc4dc8ec"
ANA_ACCOUNT = "db5eaaa2-4e98-4b73-92b7-4761b5d05052"

ADDRESS = {"street_number": "100", "street_name": "Main St", "city": "College Park", "state": "MD", "zip": "20742"}


def load_env_file() -> None:
    """Read the repo's .env into the environment (without overwriting anything already set)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip())


def created_id(response) -> str:
    """Nessie answers creates with {"objectCreated": {"_id": ...}}."""
    return response["objectCreated"]["_id"]


def find_or_make_bob(nessie: NessieClient) -> str:
    """Bob has no history with Rose, so any payment to him counts as a new payee."""
    for account in nessie.get("/accounts") or []:
        if account.get("nickname") == "Bob checking":
            return account["_id"]
    customer = created_id(nessie.post("/customers", {"first_name": "Bob", "last_name": "Stranger", "address": ADDRESS}))
    return created_id(nessie.post(f"/customers/{customer}/accounts", {
        "type": "Checking", "nickname": "Bob checking", "rewards": 0, "balance": 100,
    }))


def add_pepco_bill(nessie: NessieClient) -> None:
    bills = nessie.get(f"/accounts/{ROSE_ACCOUNT}/bills") or []
    if any("pepco" in str(b.get("payee", "")).lower() and b.get("status") != "completed" for b in bills):
        print("  Pepco bill already there.")
        return
    nessie.post(f"/accounts/{ROSE_ACCOUNT}/bills", {
        "status": "pending", "payee": "Pepco", "nickname": "Electric bill",
        "payment_date": (date.today() + timedelta(days=7)).isoformat(),
        "recurring_date": 1, "payment_amount": 85,
    })
    print("  Added the $85 Pepco bill.")


def main() -> None:
    load_env_file()
    nessie = NessieClient.from_env()

    print("Checking Rose's bills...")
    add_pepco_bill(nessie)

    print("Finding Bob...")
    bob = find_or_make_bob(nessie)

    print("\nDone! Paste these into your .env (replacing the empty ones):\n")
    print(f"NESSIE_ACCOUNT_ID={ROSE_ACCOUNT}")
    print(f'DEMO_PAYEES={{"Ana": "{ANA_ACCOUNT}", "Bob": "{bob}"}}')
    print("TRUSTED_CONTACT_NAME=Ana (daughter)")
    print("TRUSTED_CONTACT_PHONE=555-0100")


if __name__ == "__main__":
    main()
