# Backend: MCP server + app endpoints

One Python web app with two doors into the same `Bank`:

- **`/mcp`**: the MCP server the ElevenLabs agent connects to (streamable HTTP, stateless).
- **`/api/...`**: what the voice screen calls.

Every payment takes the same path: request → fraud check on the customer's real words → waits for a yes → Nessie. A held transfer can never be sent, and no tool moves money directly. Opening an account takes the same path.

This replaces the TypeScript stdio server on the `nessie-mcp` branch, and it has every capability of the `MCP_Server` on the `Nessie-framework` branch, so the ElevenLabs agent only needs this one server. ElevenLabs can only reach MCP servers over HTTP at a public URL.

## Files

| File | What it does |
|---|---|
| `nessie.py` | Nessie API client (ported from `src/nessie.ts`) |
| `bank.py` | The one door for money: transcript, payees, fraud check, pending transfers, Nessie calls |
| `app.py` | MCP tools and `/api` routes on one Starlette app |
| `server.py` | Starts it from environment variables |
| `demo_bank.py` | An in-memory Nessie for `DEMO_MODE=true` |
| `fraud_check.py`, `gemini_signals.py`, `models.py` | The fraud check (unchanged) |

## MCP tools (for the agent)

Accounts, bills, loans, and stores are named the way the customer says them ("savings", "Pepco", "auto", "CVS"). Nessie IDs never leave the server.

**Read only:**

| Tool | Returns |
|---|---|
| `get_summary` | Checking balance and the bills that are due |
| `list_accounts` | Every account with its balance |
| `get_recent_purchases(limit?, merchant_name?, account_name?)` | Purchases, newest first, optionally from one store or one account |
| `get_deposits(account_name?, limit?)`, `get_withdrawals(...)`, `get_transfers(...)` | Newest first; transfers name both ends |
| `get_bills(account_name?, recurring?, include_paid?)` | Bills still due by default; `recurring` true or false filters repeating or one-time bills |
| `get_loans` | Each loan's amount owed and monthly payment |
| `find_merchant(name)` | Category and address of a store from the customer's own purchases (at most 5; never the whole Nessie list) |

**Prepare only.** Each returns a `transfer_id` after the fraud check and waits for a yes:

| Tool | On yes, in Nessie |
|---|---|
| `request_transfer(payee_name, amount, memo?)` | Withdrawal from checking tagged `[payee:...]` (this Nessie has no working transfer between accounts) |
| `transfer_between_accounts(from_account, to_account, amount, memo?)` | Withdrawal from one of her accounts plus a deposit into the other |
| `pay_bill(biller_name, amount?, from_account?)` | Withdrawal, then the bill is marked paid, or its amount lowered after a partial payment. Never more than is owed |
| `pay_loan(loan_name?, amount?, from_account?)` | Withdrawal, then the loan's amount owed is lowered. Defaults to the monthly payment; never more than is owed |
| `withdraw(amount, memo?)`, `deposit(amount, memo?)` | Withdrawal or deposit on checking |
| `create_account(account_type, nickname?)` | New Checking, Savings, or Credit Card account with $0 |

**The yes and the no:** `confirm_payment(transfer_id)` carries out the waiting request; `cancel_payment(transfer_id)` drops it. `confirm_payment` is the only tool that changes anything in Nessie.

Payments come from checking unless `from_account` names another account. The customer's own accounts, bills, and loans count as known payees, so the new-payee rule doesn't fire on them. An account opened through this server is the exception: "open a new safe account, then move your money into it" is a common scam, so it stays a new payee. For the same reason, opening an account gets the fraud check too, and anything the check flags (a "confirm" or a "hold") stops it: nothing about opening an account is urgent, and a false stop only costs a call to Capital One.

Every tool replies with one JSON object:

```json
{"ok": true, "say": "I'll pay Maria $50.00 from your checking account. Are you sure?",
 "transfer": {"transfer_id": "t_1a2b3c4d", "kind": "transfer", "status": "awaiting_yes",
              "decision": "allow", "risk_score": 0, "reasons": [], "payee_name": "Maria",
              "amount": 50.0, "from_account_name": "Checking", "spoken_message": "..."}}
{"ok": false, "error": "That payment can't be sent.", "say": "That payment can't be sent. No money was moved."}
```

**Her words reach the check in time.** The screen posts each finished line to `/api/transcript` while the agent is already calling a tool, so a request can arrive before the words behind it. If no line came in during the last 4 seconds, a request waits up to 2 seconds for one (`WORDS_FRESH_S` and `WORDS_WAIT_S` in `bank.py`). It only waits while a screen is sending lines. At the yes, if she has said anything since the request was checked, the check runs again, and a hold then stops it before any money moves.

**"No money was moved" only when that's certain.** If Nessie refuses a payment (4xx), the request stays waiting for a yes. If the answer is lost (a timeout, a dropped connection, a 5xx), the status becomes `unknown`: it is never sent again, the reply asks her to check her balance, and the screen shows the same advice. A move between her accounts whose deposit fails after the money left is `unknown` too.

The agent reads `say` aloud and passes `transfer.transfer_id` to `confirm_payment` or `cancel_payment`. `transfer.status` is `awaiting_yes`, `held`, `executed`, `cancelled`, or `unknown`; bill and loan payments also carry `amount_owed`. List tools put the three newest items, with amounts and dates, in `say`. `transfer.kind` is `transfer`, `own_transfer`, `bill`, `loan`, `withdrawal`, `deposit`, or `new_account` (which also has `account_type`). Read tools return `summary`, `accounts`, `purchases`, `deposits`, `withdrawals`, `transfers`, `bills`, `loans`, or `merchants` in place of `transfer`.

## App endpoints (for the screen)

`POST /api/transcript`, `GET /api/transfer/current`, `POST /api/transfer/confirm`, `POST /api/transfer/cancel`, `GET /health`.

## Run it (Docker)

```bash
docker build -t technica-backend backend
docker run --env-file .env -p 8000:8000 technica-backend
```

Fill in `.env` from `.env.example`: the Nessie key, the demo checking account ID, and the payee names mapped to Nessie account IDs.

## Test it (Docker)

```bash
docker run --rm -v "$(pwd)/backend:/app" technica-backend pytest -q
```
