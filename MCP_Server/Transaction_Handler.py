"""
Simple banking operations built on NessieClient.

Each function takes an already-validated client + arguments and returns the
API's response. No validation or LLM knowledge lives here; see handler.py.

NOTE: payload fields below follow Nessie's documented shapes as I remember
them. If the API rejects a call, the NessieError body will name the field.
"""
from __future__ import annotations

from datetime import date

from Nessie_Client import NessieClient

# Nessie transaction statuses are pending / completed / cancelled.
# Change this one constant if balances don't update the way you expect.
DEFAULT_STATUS = "completed"

# For each Transaction, 
# validate transaction, get account data, format in JSON

def list_accounts(customer_id: str) -> dict:
    return {}

def get_balance(account_id: str):
    return {}
    
def deposit(account_id: str, amount: float, description: str):
    return {}
      
def withdraw(account_id: str, amount: float, description: str):
    return {}

def transfer(from_account_id: str, to_account_id: str, amount: float, description: str):
    return {}