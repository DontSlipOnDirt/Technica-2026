from __future__ import annotations

import functools
import math
import os
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal, ParamSpec, get_args

from Nessie_Client import NessieClient, NessieError  # adjust to your module names

AccountType = Literal["Checking", "Savings", "Credit Card"]
TRANSACTION_STATUS = "completed"  # Nessie: pending / completed / cancelled

_client: NessieClient | None = None


# ---- plumbing -----------------------------------------------------------

class _Failed(Exception):
    """Our own rejection (bad input, not found, not owned)."""


P = ParamSpec("P")


def _respond(fn: Callable[P, Any]) -> Callable[P, dict[str, Any]]:
    """Wrap a function's return value (or exception) into the status dict.
    Typed with ParamSpec so type checkers see the original parameters and a
    dict return, rather than the raw data the function itself returns."""
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        try:
            return {"status": "success", "raw": fn(*args, **kwargs)}
        except _Failed as exc:
            return {"status": "failed", "raw": {"error": str(exc)}}
        except NessieError as exc:
            return {"status": "failed",
                    "raw": {"error": str(exc), "http_status": exc.status, "body": exc.body}}
        except Exception as exc:
            return {"status": "failed", "raw": {"error": f"{type(exc).__name__}: {exc}"}}
    return wrapper


def _get_client() -> NessieClient:
    global _client
    if _client is None:
        # NessieClient has no default key; Nessie_Client already loaded .env into the environment.
        _client = NessieClient(api_key=os.environ.get("NESSIE_API_KEY"))
    return _client


def _today() -> str:
    return date.today().isoformat()


def _opt(value: Any) -> str | None:
    """Optional string parameter: None and "" both mean 'not provided'."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required(value: Any, name: str) -> str:
    cleaned = _opt(value)
    if cleaned is None:
        raise _Failed(f"{name} is required")
    return cleaned


def _check_amount(value: Any, name: str = "amount", allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Failed(f"{name} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise _Failed(f"{name} must be finite")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise _Failed(f"{name} is not a valid number")
    if dec < 0 or (dec == 0 and not allow_zero):
        raise _Failed(f"{name} must be greater than 0" if not allow_zero
                      else f"{name} cannot be negative")
    if dec != dec.quantize(Decimal("0.01")):
        raise _Failed(f"{name} can have at most 2 decimal places")
    return float(dec)


def _as_list(response: Any) -> list:
    if not isinstance(response, list):
        raise _Failed(f"Unexpected API response (expected a list): {str(response)[:200]}")
    return response


def _customer_accounts(client: NessieClient, customer_id: str) -> list:
    return _as_list(client.get(f"customers/{customer_id}/accounts"))


def _require_owned(owned_ids: list[str], account_id: str, label: str = "Account") -> None:
    if account_id not in owned_ids:
        raise _Failed(f"{label} {account_id} was not found for this customer")


def _collect(client: NessieClient, account_ids: list[str], subresource: str) -> list:
    records: list = []
    for aid in account_ids:
        records.extend(_as_list(client.get(f"accounts/{aid}/{subresource}")))
    return records


def _find(records: list, record_id: str, label: str) -> dict:
    for record in records:
        if record.get("_id") == record_id:
            return record
    raise _Failed(f"{label} {record_id} was not found for this customer")


def _list_or_one(customer_id: str, subresource: str, label: str,
                 account_id: str | None, record_id: str | None):
    """Shared logic for deposits/withdrawals/transfers/purchases/bills/loans."""
    client = _get_client()
    owned_ids = [a["_id"] for a in _customer_accounts(client, customer_id)]
    if record_id:                       # one record; filters ignored
        return _find(_collect(client, owned_ids, subresource), record_id, label)
    if account_id:                      # list for one account
        _require_owned(owned_ids, account_id)
        owned_ids = [account_id]
    return _collect(client, owned_ids, subresource)


def _number_or_none(value: Any) -> float | None:
    """The value as a float if it's a real number (not bool), else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _is_recurring(bill: dict) -> bool:
    # Assumption: a recurring bill has a recurring_date or status "recurring".
    return bool(bill.get("recurring_date")) or bill.get("status") == "recurring"


def _try_update(client: NessieClient, path: str, payload: dict) -> dict:
    """Best-effort PUT used after money has already moved: report, don't raise."""
    try:
        return client.put(path, json=payload)
    except NessieError as exc:
        return {"error": str(exc), "http_status": exc.status, "body": exc.body}


def _withdrawal_payload(amount: float, description: str) -> dict:
    return {"medium": "balance", "transaction_date": _today(),
            "status": TRANSACTION_STATUS, "amount": amount, "description": description}


# ---- Reads --------------------------------------------------------------

@_respond
def get_accounts(customer_id: str, account_id: str | None = None,
                 account_type: AccountType | None = None):
    """One account (with balance) if account_id is given; otherwise all of the
    customer's accounts, optionally only those of account_type."""
    account_id = _opt(account_id)
    type_filter = _opt(account_type)  # new name: _opt returns str, not AccountType
    accounts = _customer_accounts(_get_client(), customer_id)
    if account_id:
        return _find(accounts, account_id, "Account")
    if type_filter:
        accounts = [a for a in accounts if a.get("type") == type_filter]
    return accounts


@_respond
def get_deposits(customer_id: str, account_id: str | None = None,
                 deposit_id: str | None = None):
    """One deposit if deposit_id is given; otherwise deposits for account_id,
    or across all of the customer's accounts."""
    return _list_or_one(customer_id, "deposits", "Deposit",
                        _opt(account_id), _opt(deposit_id))


@_respond
def get_withdrawals(customer_id: str, account_id: str | None = None,
                    withdrawal_id: str | None = None):
    """One withdrawal if withdrawal_id is given; otherwise withdrawals for
    account_id, or across all of the customer's accounts."""
    return _list_or_one(customer_id, "withdrawals", "Withdrawal",
                        _opt(account_id), _opt(withdrawal_id))


@_respond
def get_transfers(customer_id: str, account_id: str | None = None,
                  transfer_id: str | None = None):
    """One transfer if transfer_id is given; otherwise transfers for
    account_id, or across all of the customer's accounts."""
    return _list_or_one(customer_id, "transfers", "Transfer",
                        _opt(account_id), _opt(transfer_id))


@_respond
def get_purchases(customer_id: str, account_id: str | None = None,
                  purchase_id: str | None = None, merchant_id: str | None = None):
    """One purchase if purchase_id is given; otherwise purchases, optionally
    narrowed to account_id and/or merchant_id."""
    purchase_id, merchant_id = _opt(purchase_id), _opt(merchant_id)
    result = _list_or_one(customer_id, "purchases", "Purchase", _opt(account_id), purchase_id)
    if not purchase_id and merchant_id:
        result = [p for p in result if p.get("merchant_id") == merchant_id]
    return result


@_respond
def get_bills(customer_id: str, account_id: str | None = None,
              bill_id: str | None = None, recurring: bool | None = None):
    """One bill if bill_id is given; otherwise bills, optionally narrowed to
    account_id and/or recurring (True = recurring only, False = one-time only,
    None = both)."""
    bill_id = _opt(bill_id)
    result = _list_or_one(customer_id, "bills", "Bill", _opt(account_id), bill_id)
    if not bill_id and recurring is not None:
        result = [b for b in result if _is_recurring(b) == recurring]
    return result


@_respond
def get_loans(customer_id: str, account_id: str | None = None,
              loan_id: str | None = None):
    """One loan if loan_id is given; otherwise loans for account_id, or across
    all of the customer's accounts."""
    return _list_or_one(customer_id, "loans", "Loan", _opt(account_id), _opt(loan_id))


@_respond
def get_merchants(merchant_id: str | None = None):
    """One merchant if merchant_id is given; otherwise all merchants. Merchants
    are shared data, so there is no customer_id or ownership check."""
    merchant_id = _opt(merchant_id)
    return _get_client().get(f"merchants/{merchant_id}" if merchant_id else "merchants")


# ---- Actions that change data -------------------------------------------

@_respond
def create_account(customer_id: str, account_type: AccountType, nickname: str,
                   starting_balance: float = 0.0):
    """Open a new account for the customer."""
    type_value = _required(account_type, "account_type")
    if type_value not in get_args(AccountType):
        raise _Failed(f"account_type must be one of {list(get_args(AccountType))}")
    nickname = _required(nickname, "nickname")
    balance = _check_amount(starting_balance, "starting_balance", allow_zero=True)
    return _get_client().post(f"customers/{customer_id}/accounts", json={
        "type": type_value, "nickname": nickname, "rewards": 0, "balance": balance})


@_respond
def make_transfer(customer_id: str, from_account_id: str, to_account_id: str,
                  amount: float, description: str = "Transfer"):
    """Move money between two different accounts, both of which must belong to
    the customer."""
    from_id = _required(from_account_id, "from_account_id")
    to_id = _required(to_account_id, "to_account_id")
    amount = _check_amount(amount)
    if from_id == to_id:
        raise _Failed("Cannot transfer to the same account")

    client = _get_client()
    owned_ids = [a["_id"] for a in _customer_accounts(client, customer_id)]
    _require_owned(owned_ids, from_id)
    _require_owned(owned_ids, to_id)

    return client.post(f"accounts/{from_id}/transfers", json={
        "medium": "balance", "payee_id": to_id, "transaction_date": _today(),
        "status": TRANSACTION_STATUS, "amount": amount,
        "description": _opt(description) or "Transfer"})


@_respond
def pay_bill(customer_id: str, bill_id: str, from_account_id: str, amount: float):
    """Pay a bill from one of the customer's accounts: withdraws the money, then
    (best effort) marks a fully paid one-time bill as completed."""
    bill_id = _required(bill_id, "bill_id")
    from_id = _required(from_account_id, "from_account_id")
    amount = _check_amount(amount)

    client = _get_client()
    owned_ids = [a["_id"] for a in _customer_accounts(client, customer_id)]
    _require_owned(owned_ids, from_id)
    bill = _find(_collect(client, owned_ids, "bills"), bill_id, "Bill")

    owed = _number_or_none(bill.get("payment_amount"))
    if owed is not None and amount > owed:
        raise _Failed(f"Amount {amount} is more than the amount owed ({owed})")

    payee = bill.get("payee") or bill_id
    withdrawal = client.post(f"accounts/{from_id}/withdrawals",
                             json=_withdrawal_payload(amount, f"Bill payment: {payee}"))

    if _is_recurring(bill):
        update: Any = "skipped (recurring bill)"
    elif owed is not None and amount < owed:
        update = "skipped (partial payment)"
    else:
        update = _try_update(client, f"bills/{bill_id}",
                             {"status": "completed", "payment_date": _today()})
    return {"withdrawal": withdrawal, "bill_update": update}


@_respond
def pay_loan(customer_id: str, loan_id: str, from_account_id: str, amount: float):
    """Make a payment on a loan from one of the customer's accounts: withdraws
    the money, then (best effort) reduces the loan's remaining amount."""
    loan_id = _required(loan_id, "loan_id")
    from_id = _required(from_account_id, "from_account_id")
    amount = _check_amount(amount)

    client = _get_client()
    owned_ids = [a["_id"] for a in _customer_accounts(client, customer_id)]
    _require_owned(owned_ids, from_id)
    loan = _find(_collect(client, owned_ids, "loans"), loan_id, "Loan")

    owed = _number_or_none(loan.get("amount"))
    if owed is not None and amount > owed:
        raise _Failed(f"Amount {amount} is more than the amount owed ({owed})")

    withdrawal = client.post(f"accounts/{from_id}/withdrawals",
                             json=_withdrawal_payload(amount, f"Loan payment: {loan_id}"))

    if owed is not None:
        remaining = round(owed - amount, 2)
        payload: dict = {"amount": remaining}
        if remaining == 0:
            payload["status"] = "completed"
        update: Any = _try_update(client, f"loans/{loan_id}", payload)
    else:
        update = "skipped (remaining amount unknown)"
    return {"withdrawal": withdrawal, "loan_update": update}