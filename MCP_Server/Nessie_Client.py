"""
A small client for Capital One's Nessie (hackathon) banking API.

Usage:
    python nessie_client.py
"""
from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import os
from dotenv import load_dotenv

load_dotenv()  # reads .env into environment variables

BASE_URL = os.environ.get("NESSIE_BASE_URL", "https://prod-api.nessieisreal.com")
API_KEY = os.environ.get("NESSIE_API_KEY")

class NessieError(Exception):
    """Raised for any non-2xx response from the API."""

    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.body = body


class NessieClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL,
                 timeout: float = 10.0):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("NESSIE_API_KEY is not set. Add it to your .env file.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "PUT", "DELETE"}),  # not POST: not idempotent
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

        # Resource handles
        self.customers = Customers(self)
        self.accounts = Accounts(self)
        self.purchases = AccountSubresource(self, "purchases")
        self.deposits = AccountSubresource(self, "deposits")
        self.withdrawals = AccountSubresource(self, "withdrawals")
        self.transfers = AccountSubresource(self, "transfers")
        self.bills = AccountSubresource(self, "bills")

    # ---- core request layer -------------------------------------------
    def request(self, method: str, path: str, *, params: dict | None = None,
                json: dict | None = None) -> Any:
        params = {**(params or {}), "key": self.api_key}
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self.session.request(method, url, params=params, json=json,
                                        timeout=self.timeout)
        except requests.RequestException as exc:
            raise NessieError(0, f"Network error: {exc}") from exc

        try:
            body = resp.json() if resp.content else None
        except ValueError:
            body = resp.text

        if not resp.ok:
            msg = body.get("message") if isinstance(body, dict) else str(body)
            raise NessieError(resp.status_code, msg or resp.reason, body)
        return body

    def get(self, path, **kw):    return self.request("GET", path, **kw)
    def post(self, path, **kw):   return self.request("POST", path, **kw)
    def put(self, path, **kw):    return self.request("PUT", path, **kw)
    def delete(self, path, **kw): return self.request("DELETE", path, **kw)


# ---- resources ----------------------------------------------------------
class Customers:
    def __init__(self, c: NessieClient): self.c = c
    def list(self):                 return self.c.get("customers")
    def get(self, customer_id):     return self.c.get(f"customers/{customer_id}")
    def create(self, data: dict):   return self.c.post("customers", json=data)
    def update(self, customer_id, data: dict):
        return self.c.put(f"customers/{customer_id}", json=data)
    def accounts(self, customer_id):
        return self.c.get(f"customers/{customer_id}/accounts")


class Accounts:
    def __init__(self, c: NessieClient): self.c = c
    def list(self):                 return self.c.get("accounts")
    def get(self, account_id):      return self.c.get(f"accounts/{account_id}")
    def create(self, customer_id, data: dict):
        return self.c.post(f"customers/{customer_id}/accounts", json=data)
    def update(self, account_id, data: dict):
        return self.c.put(f"accounts/{account_id}", json=data)
    def delete(self, account_id):   return self.c.delete(f"accounts/{account_id}")


class AccountSubresource:
    """Purchases, deposits, withdrawals, transfers, bills all hang off an account."""

    def __init__(self, c: NessieClient, name: str):
        self.c, self.name = c, name

    def list(self, account_id):
        return self.c.get(f"accounts/{account_id}/{self.name}")

    def get(self, item_id):
        return self.c.get(f"{self.name}/{item_id}")

    def create(self, account_id, data: dict):
        return self.c.post(f"accounts/{account_id}/{self.name}", json=data)

    def update(self, item_id, data: dict):
        return self.c.put(f"{self.name}/{item_id}", json=data)

    def delete(self, item_id):
        return self.c.delete(f"{self.name}/{item_id}")


# ---- demo ---------------------------------------------------------------
if __name__ == "__main__":
    nessie = NessieClient(api_key= API_KEY, base_url="https://prod-api.nessieisreal.com")
    try:
        customers = nessie.customers.list()
        print("Response type:", type(customers).__name__)
        print("Raw response:", customers)

        if isinstance(customers, list) and not customers:
            print("No customers on this key, creating one...")
            created = nessie.customers.create({
                "first_name": "Ada",
                "last_name": "Lovelace",
                "address": {
                    "street_number": "1",
                    "street_name": "Main St",
                    "city": "Chillum",
                    "state": "MD",
                    "zip": "20782",
                },
            })
            print("Create response:", created)
            customers = nessie.customers.list()

        for cust in customers[:3]:
            print(cust["_id"], cust.get("first_name"), cust.get("last_name"))
    except NessieError as e:
        print("API error:", e, "| body:", e.body)