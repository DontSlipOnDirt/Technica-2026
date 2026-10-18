# Technica-2026 Voice Banking MCP

**What runs today:** `frontend/` (the React voice app) and `backend/` (the Python MCP server
and app endpoints, deployed to Render; see [backend/README.md](backend/README.md)).
The TypeScript server described below (`src/`) and the `MCP_Server/` stubs are earlier
versions kept for reference; `backend/` replaces both.

Strombus, the ElevenLabs voice agent, has its system prompt versioned in [docs/elevenlabs-agent-prompt.md](docs/elevenlabs-agent-prompt.md).
The live agent uses its published ElevenLabs dashboard configuration; this Markdown file is a
reference copy and is not loaded automatically by the frontend or backend. Apply prompt changes
in ElevenLabs and publish the agent for new conversations to use them.

---

This project contains the first backend slice of an accessible voice-banking prototype. It exposes a Model Context Protocol server that calls the Capital One Nessie simulation API. Nessie credentials stay in the server process and are never sent to the model or mobile client.

## Official API reference

The implementation targets the REST resources documented at [nessieisreal.com/docs](https://nessieisreal.com/docs). Nessie is a mock banking API; this project is not connected to real bank accounts.

## Setup

1. Install Node.js 20 or newer.
2. Copy `.env.example` to `.env`.
3. Set `NESSIE_API_KEY` to a key from the Nessie developer portal.
4. Install dependencies with `npm install`.
5. Verify the project with `npm test`.

## Run the MCP server

```powershell
npm start
```

The server uses stdio transport so it can be registered by an MCP-compatible client. It does not start an HTTP port.

## Available tools

- `get_customer_accounts`: list a customer's accounts.
- `list_customers`: search the customer directory by name.
- `get_customer`: retrieve a customer profile.
- `get_account`: retrieve an account and balance.
- `list_account_activity`: list purchases, transfers, deposits, withdrawals, or bills.
- `find_merchants`: search the Nessie merchant directory.
- `get_merchant`: retrieve a merchant profile.
- `list_atms`: find ATM locations.
- `list_branches`: find branch locations.
- `create_transfer`: create a transfer only when `confirmed` is `true` and a fresh `idempotencyKey` is supplied.

The confirmation and idempotency fields are protocol safeguards, not a replacement for backend authorization. The future API/orchestration layer must verify the active user owns the source account and must require a visible confirmation in the mobile app.

## MCP client configuration

An MCP client should launch the server from the repository directory and provide the environment variable:

```json
{
	"mcpServers": {
		"nessie-banking": {
			"command": "npm",
			"args": ["start"],
			"env": {
				"NESSIE_API_KEY": "replace-with-your-key"
			}
		}
	}
}
```
