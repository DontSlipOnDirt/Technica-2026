# Backend: MCP server + app endpoints

One Python web app with two doors into the same `Bank`:

- **`/mcp`**: the MCP server the ElevenLabs agent connects to (streamable HTTP, stateless).
- **`/api/...`**: what the voice screen calls.

Every payment takes the same path: request → fraud check on the customer's real words → waits for a yes → Nessie. A held transfer can never be sent, and no tool moves money directly.

This replaces the TypeScript stdio server on the `nessie-mcp` branch. ElevenLabs can only reach MCP servers over HTTP at a public URL.

## Files

| File | What it does |
|---|---|
| `nessie.py` | Nessie API client (ported from `src/nessie.ts`) |
| `bank.py` | The one door for money: transcript, payees, fraud check, pending transfers, Nessie calls |
| `app.py` | MCP tools and `/api` routes on one Starlette app |
| `server.py` | Starts it from environment variables |
| `fraud_check.py`, `gemini_signals.py`, `models.py` | The fraud check (unchanged) |

## MCP tools (for the agent)

`get_summary`, `list_accounts`, `get_recent_purchases`, `request_transfer(payee_name, amount, memo)`, `pay_bill(biller_name, amount?)`, `withdraw(amount, memo)`, `deposit(amount, memo)`, `confirm_payment(transfer_id)`, `cancel_payment(transfer_id)`. `withdraw` and `deposit` take the same request → fraud check → yes path as transfers.

Every tool replies with one JSON object:

```json
{"ok": true, "say": "I'll pay Maria $50.00 from your checking account. Are you sure?",
 "transfer": {"transfer_id": "t_1a2b3c4d", "kind": "transfer", "status": "awaiting_yes",
              "decision": "allow", "risk_score": 0, "reasons": [], "payee_name": "Maria",
              "amount": 50.0, "from_account_name": "Checking", "spoken_message": "..."}}
{"ok": false, "error": "That payment can't be sent.", "say": "That payment can't be sent. No money was moved."}
```

The agent reads `say` aloud and passes `transfer.transfer_id` to `confirm_payment` or `cancel_payment`. Read tools return `summary` or `purchases` in place of `transfer`.

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
