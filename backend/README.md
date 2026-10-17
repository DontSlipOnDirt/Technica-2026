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

`get_summary`, `get_recent_purchases`, `request_transfer(payee_name, amount, memo)`, `pay_bill(biller_name, amount?)`, `confirm_payment(transfer_id)`, `cancel_payment(transfer_id)`.

Every tool returns a sentence or JSON the agent can read aloud. Failures end with "No money was moved."

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
