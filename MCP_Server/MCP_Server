"""
MCP server exposing the Nessie banking functions as tools.

An ElevenLabs agent connects to this server's URL, lists the tools below,
and calls them. MCP handles the request format and argument schemas, so
handler.py's validation and transactions.py stay exactly as they are.

Run:
    python -m pip install "mcp[cli]"
    python mcp_server.py          # serves http://0.0.0.0:8000/mcp
"""
from mcp.server.mcpserver import MCPServer

import os
from typing import Literal

import Transaction_Handler as Handler


mcp = MCPServer("nessie-banking")

# Without it every call would ask Nessie about customer "None"; fail at startup instead.
CUSTOMER_ID = os.environ.get("BASE_CUSTOMER_ID", "").strip()
if not CUSTOMER_ID:
    raise RuntimeError("BASE_CUSTOMER_ID is required (the demo customer's Nessie ID)")

AccountType = Literal["Checking", "Savings", "Credit Card"]


# ---- Read tools ---------------------------------------------------------

@mcp.tool()
def get_accounts(account_id: str | None = None,
                 account_type: AccountType | None = None) -> dict:
    """Get the customer's bank accounts. With account_id, returns that one
    account including its balance. Without it, lists all accounts, optionally
    only those of one account_type (Checking, Savings or Credit Card)."""
    return Handler.get_accounts(CUSTOMER_ID, account_id=account_id,
                                account_type=account_type)


@mcp.tool()
def get_deposits(account_id: str | None = None,
                 deposit_id: str | None = None) -> dict:
    """Get deposits. With deposit_id, returns that one deposit. Without it,
    lists deposits for the given account_id, or across all of the customer's
    accounts if no account_id is given."""
    return Handler.get_deposits(CUSTOMER_ID, account_id=account_id,
                                deposit_id=deposit_id)


@mcp.tool()
def get_withdrawals(account_id: str | None = None,
                    withdrawal_id: str | None = None) -> dict:
    """Get withdrawals. With withdrawal_id, returns that one withdrawal.
    Without it, lists withdrawals for the given account_id, or across all of
    the customer's accounts if no account_id is given."""
    return Handler.get_withdrawals(CUSTOMER_ID, account_id=account_id,
                                   withdrawal_id=withdrawal_id)


@mcp.tool()
def get_transfers(account_id: str | None = None,
                  transfer_id: str | None = None) -> dict:
    """Get transfers between accounts. With transfer_id, returns that one
    transfer. Without it, lists transfers for the given account_id, or across
    all of the customer's accounts if no account_id is given."""
    return Handler.get_transfers(CUSTOMER_ID, account_id=account_id,
                                 transfer_id=transfer_id)


@mcp.tool()
def get_purchases(account_id: str | None = None,
                  purchase_id: str | None = None,
                  merchant_id: str | None = None) -> dict:
    """Get purchases. With purchase_id, returns that one purchase. Without it,
    lists purchases, optionally limited to one account_id and/or one
    merchant_id. If you only know a merchant's name, call get_merchants first
    to find its ID."""
    return Handler.get_purchases(CUSTOMER_ID, account_id=account_id,
                                 purchase_id=purchase_id, merchant_id=merchant_id)


@mcp.tool()
def get_bills(account_id: str | None = None,
              bill_id: str | None = None,
              recurring: bool | None = None) -> dict:
    """Get bills. With bill_id, returns that one bill. Without it, lists bills,
    optionally limited to one account_id, and optionally only recurring bills
    (recurring=true) or only one-time bills (recurring=false). Leave recurring
    out to get both."""
    return Handler.get_bills(CUSTOMER_ID, account_id=account_id,
                             bill_id=bill_id, recurring=recurring)


@mcp.tool()
def get_loans(account_id: str | None = None,
              loan_id: str | None = None) -> dict:
    """Get loans. With loan_id, returns that one loan. Without it, lists loans
    for the given account_id, or across all of the customer's accounts if no
    account_id is given."""
    return Handler.get_loans(CUSTOMER_ID, account_id=account_id, loan_id=loan_id)


@mcp.tool()
def get_merchants(merchant_id: str | None = None) -> dict:
    """Get merchants. With merchant_id, returns that one merchant. Without it,
    lists all known merchants with their IDs and names."""
    return Handler.get_merchants(merchant_id=merchant_id)


# ---- Actions that change data (kept separate, one purpose each) ---------

@mcp.tool()
def create_account(account_type: AccountType, nickname: str,
                   starting_balance: float = 0.0) -> dict:
    """Open a new account for the customer. Amounts are in dollars with at most
    2 decimal places. This changes data, so confirm the details with the
    customer before calling it."""
    return Handler.create_account(CUSTOMER_ID, account_type=account_type,
                                  nickname=nickname,
                                  starting_balance=starting_balance)


@mcp.tool()
def make_transfer(from_account_id: str, to_account_id: str, amount: float,
                  description: str = "Transfer") -> dict:
    """Move money from one account to a different account. Amount is in dollars
    with at most 2 decimal places. This moves money, so confirm the accounts and
    amount with the customer before calling it."""
    return Handler.make_transfer(CUSTOMER_ID, from_account_id=from_account_id,
                                 to_account_id=to_account_id, amount=amount,
                                 description=description)


@mcp.tool()
def pay_bill(bill_id: str, from_account_id: str, amount: float) -> dict:
    """Pay a bill from one of the customer's accounts. Look up the bill_id and
    the amount owed with get_bills first. Amount is in dollars with at most 2
    decimal places. This moves money, so confirm the bill, the account and the
    amount with the customer before calling it."""
    return Handler.pay_bill(CUSTOMER_ID, bill_id=bill_id,
                            from_account_id=from_account_id, amount=amount)

 
@mcp.tool()
def pay_loan(loan_id: str, from_account_id: str, amount: float) -> dict:
    """Make a payment on a loan from one of the customer's accounts. Look up the
    loan_id and the payment amount with get_loans first. Amount is in dollars
    with at most 2 decimal places. This moves money, so confirm the loan, the
    account and the amount with the customer before calling it."""
    return Handler.pay_loan(CUSTOMER_ID, loan_id=loan_id,
                            from_account_id=from_account_id, amount=amount)

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )