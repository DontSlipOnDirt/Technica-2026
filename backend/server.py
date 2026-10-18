# server.py
# Starts the backend from environment variables (see .env.example at the repo root).
#   docker build -t technica-backend backend
#   docker run --env-file .env -p 8000:8000 technica-backend
# ElevenLabs needs a public URL for /mcp: deploy it, or tunnel port 8000 (e.g. ngrok) while testing.

import json
import os

from app import create_app, origins_from_env
from bank import Bank, DemoConfig
from models import TrustedContact
from nessie import NessieClient


def load_config() -> DemoConfig:
    account_id = os.environ.get("NESSIE_ACCOUNT_ID")
    if not account_id:
        raise RuntimeError("NESSIE_ACCOUNT_ID is required (the demo customer's checking account)")
    payees = json.loads(os.environ.get("DEMO_PAYEES", "{}"))
    contact_name = os.environ.get("TRUSTED_CONTACT_NAME")
    return DemoConfig(
        account_id=account_id,
        account_name=os.environ.get("ACCOUNT_NAME", "Checking"),
        payees={name.lower(): nessie_id for name, nessie_id in payees.items()},
        trusted_contact=TrustedContact(contact_name, os.environ.get("TRUSTED_CONTACT_PHONE", "")) if contact_name else None,
    )


def build_bank() -> Bank:
    # DEMO_MODE=true: a built-in pretend bank, for testing the agent without Nessie.
    if os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true", "yes"):
        from demo_bank import DEMO_CONFIG, DemoNessie
        return Bank(DemoNessie(), DEMO_CONFIG)
    return Bank(NessieClient.from_env(), load_config())


mcp, app = create_app(build_bank(), origins_from_env())
