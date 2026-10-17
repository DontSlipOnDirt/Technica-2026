# Voice Banking Screen — Design

Owner: app person (Nic). Date: 2026-10-17. Hackathon: Technica 2026.

## Intent

A voice assistant feature that would live inside the Capital One mobile app. A customer, especially an older adult or someone with poor eyesight, taps a microphone, asks about their money or asks to pay or send money, and hears the answer. Every money-moving request goes through the team's fraud check first. If the request looks like a scam, the money does not move, and nothing in the app can make it move: the customer is told why and given Capital One's phone number.

We are pitching a **feature that plugs into the existing Capital One app**, not a new app. So the deliverable is **one screen**: the voice panel the customer would land on after opening it from inside the Capital One app.

## Goals

- One mobile-sized screen that looks like it belongs in the Capital One app (their logo, colors, button style).
- Talk to the agent by tapping a mic circle that pulses while it listens, Google-assistant style.
- A live chat transcript under the circle showing both sides.
- Read-only questions (spending, balance, bills due) are answered in the chat with no confirmation step.
- Money-moving requests (pay a bill, send money) always end in a clear "Are you sure?" moment with big Yes / No buttons, answerable by voice or tap.
- A scam that the fraud check stops is shown clearly and **cannot be overridden from the app**.
- Works on a phone in the demo; deployable on Vercel.

## Non-goals (this build)

- No home screen, balance page, menus, login, or navigation. The rest of the Capital One app is assumed to exist.
- No family/trusted-contact alert screen. The idea stays in the pitch; it is not built now.
- No PIN release of a held transfer. (The fraud check teammate's `release_hold` is dropped.)
- No manual "choose your bill on screen" fallback when voice fails.
- No custom turn-taking logic. ElevenLabs decides when the customer has finished speaking.

## Anti-goals (would make it a failure even if it "works")

- Any path — voice, tap, retry, or agent reasoning — that lets a `hold` transfer go through.
- The screen saying money was sent before the backend confirms it actually was.
- The agent's own wording of the request being what the fraud check scans, instead of what the customer actually said (hence transcript forwarding).
- The Capital One / ElevenLabs / Gemini / Nessie secret keys reaching the browser.
- Looking like a generic chatbot rather than a Capital One feature.

## The one screen and its four looks

Mockups were reviewed in the brainstorm companion (`.superpowers/brainstorm/.../content/main-screens-v4.html` and `confirm-screens-v2.html`).

Common to all looks, top to bottom:
1. Header: Capital One logo (SVG pulled from capitalone.com, saved at `.superpowers/brainstorm/1352-1792265007/content/capitalone-logo.svg`; copy into the app's assets) on the left, the word "Voice" on the right.
2. The mic circle.
3. A status line under the circle ("Listening…", "Say yes or no", "Transfer stopped").
4. A middle area that changes per look (empty, Are-you-sure panel, Sent box, Scam box).
5. The chat transcript, filling the rest of the screen, newest at the bottom; user bubbles right in navy, agent bubbles left in white.

### 1. Talking
- Idle: the circle is still. Tapping it starts the voice session.
- Listening/speaking: colored rings pulse around the navy mic.
- Tapping the circle while she is talking ends her turn. Otherwise ElevenLabs decides when her turn is over. If the SDK has no way to force the turn to end, tapping mutes the mic, which ElevenLabs then treats as silence; that is acceptable.
- Read-only answers just appear in the chat and are spoken.

### 2. Are you sure?
- Appears when a pay/send request has passed the fraud check (`allow` or `confirm`).
- Shows the payment in large text, e.g. "Pay Pepco $600.00 from Checking?".
- If the decision is `confirm`, shows the fraud check's reasons in a slim yellow warning bar above the buttons.
- Two stacked full-width buttons: green **✓ Yes, pay it**, Capital One red (`#d03027`) **✕ No, cancel**. Square-ish 4px corners, ~56px tall, 20px semi-bold text, Helvetica fallback for Capital One's Optimist font.
- The agent says the same thing aloud ("I'll pay Pepco $600.00 from your checking account. Are you sure?").
- Saying yes and tapping Yes do exactly the same thing. Same for no.

### 3. Sent
- Green box: "✓ Your electric bill of $600.00 has been sent." Only shown after the backend reports the money actually moved.
- Agent asks "Is there anything else I can help with?". If she says no, the agent says goodbye and the session ends (circle goes still).

### 4. Scam caught
- Circle turns red with a shield icon; status "Transfer stopped".
- Red-bordered box: "This looks like a scam", "We stopped your $X transfer. Your money has not moved.", the fraud check's reasons as bullets, and a large **Call Capital One** button (`tel:` link) with the number. Use Capital One's real customer service number from capitalone.com; the mockup used a placeholder.
- The agent reads the fraud check's `spoken_message` word for word.
- There is no button, voice command, or retry that releases it.
- **The conversation stays open.** She can keep asking questions (balance, spending). The red box stays until she starts a different request.
- **No amount of reasoning with the agent unblocks it.** This is enforced by the system, not by the agent's good behavior:
  - A held `transfer_id` can never be confirmed; the backend rejects it.
  - If she (or a scammer coaching her) asks again — "send it anyway", "it's fine, I know them", a smaller amount, a different wording — the agent can only call `request_transfer` again, which runs the fraud check again on **all** of her words in the session, so the scam story is still there.
  - Once a payee has been held in a session, every further request to that payee in the same session is held automatically, whatever the amount or wording.
  - Agent prompt (voice teammate): after a hold, don't argue, don't offer workarounds, repeat that Capital One will never ask her to move money to keep it safe, and point to the Call Capital One button.

### Failures
- Any failure (backend down, Nessie error, insufficient funds, payee not found) shows a chat message ending in the standard sentence **"No money was moved."**

## How it works (the parts decided)

- **Voice:** ElevenLabs Agents, run in the browser with `@elevenlabs/react` (`useConversation`). The voice teammate configures the agent in the ElevenLabs dashboard and chooses a Gemini model as its LLM there. The agent is public so the app needs only the agent ID, never an ElevenLabs key.
- **Tools live on an MCP server (required).** The backend exposes an MCP server (Python, FastMCP, stateless streamable HTTP, on Vercel at a public URL). It is added in the ElevenLabs dashboard as a custom MCP server and attached to the agent. MCP must be enabled for the ElevenLabs workspace first. Tools are set to **auto-approved** so the voice flow never stops for approval prompts; safety comes from the fraud check and confirm-by-ID, not approval.
- **MCP tools:** `get_summary()`, `get_recent_purchases(days)`, `request_transfer(payee_name, amount, memo)`, `pay_bill(biller_name, amount?)`, `confirm_payment(transfer_id)`, `cancel_payment(transfer_id)`. Each calls the same backend functions as the HTTP endpoints — one door for money. Tools take names, not IDs; the backend looks up the Nessie account ID.
- **Transcript forwarding gives the fraud check her real words.** The MCP server never sees the conversation, so the app sends every finished user line to `POST /api/transcript` (with the ElevenLabs `conversation_id` from `startSession`). When `request_transfer` / `pay_bill` run, the backend uses **every user line stored for the most recent conversation**, joined with spaces, as `user_said`. The agent never supplies `user_said`.
- **The app checks for the pending transfer.** While a session is active, the app calls `GET /api/transfer/current` once a second and shows the panel for whatever it returns: `awaiting_yes` → Are-you-sure, `held` → scam caught, `executed` → sent, `cancelled` or nothing → no panel.
- **Pending action by ID.** Yes confirms by `transfer_id` only; the backend sends exactly what it stored. A new money request cancels any older pending one. Confirming the same ID twice must not pay twice. A held ID can never be confirmed.
- **Voice yes and tap yes:** the agent calls the `confirm_payment` / `cancel_payment` MCP tools; the Yes/No buttons call `POST /api/transfer/confirm` / `cancel` directly. Both land on the same backend function. After a tap, the app tells the agent the outcome with `sendContextualUpdate` so it can say "Done" and ask if there's anything else. Prompt rule for the agent: only a clear yes counts; if unsure, ask again.
- **Read vs write is structural:** read tools return data; write tools can only create a pending action. There is no tool that moves money directly.
- **Turn-taking:** deferred to ElevenLabs (e.g. its "patient" setting). Tap-the-circle-to-finish is the explicit override.
- **Stack:** React + Vite in `frontend/`, deployed to Vercel in the same project as the Python backend and MCP server. Brand navy `#013d5b`, red `#d03027`.
- **Stand-in API:** until the backend exists, a fake API in the app stores transcript lines, runs made-up fraud rules (`hold` when her words mention "safe account", the amount is over $1,000, or the payee was already held; `confirm` between $300 and $1,000; `allow` otherwise), and exposes a `simulateRequest` helper that plays the MCP server's part so the app can be tested without ElevenLabs or a backend.

## Backend contract the screen depends on

Owned by teammates; listed so the app and backend agree. All JSON is snake_case, money is dollars as decimals, dates `2026-10-17T14:32:00`, errors `{"error": "message"}`.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/transcript` | `conversation_id`, `text` | `{"ok": true}` |
| `GET /api/transfer/current` | — | `{"transfer": null}` or `{"transfer": {transfer_id, kind, status, decision, risk_score, reasons, spoken_message, payee_name, amount, from_account_name}}`; `status` is `"awaiting_yes"`, `"held"`, `"executed"`, or `"cancelled"` |
| `POST /api/transfer/confirm` | `transfer_id` | `{"status": "executed"}` or `{"error": ...}` |
| `POST /api/transfer/cancel` | `transfer_id` | `{"status": "cancelled"}` |

The MCP tools above are the agent's side of the same backend. `POST /transfer/release` and `GET /alerts` from the original contract are not used.

## Calls made by Claude (check these)

- **`user_said` = every user line stored for the most recent conversation**, not just the last turn. Scam coaching often comes several turns before the amount. The demo has one active conversation at a time; supporting several at once would need the MCP tools to know which conversation called them, which ElevenLabs' docs don't promise.
- **No app-side "did she really say yes" classifier.** Voice yes relies on the agent's prompt rule; the real protection is that only fraud-approved pending actions can be confirmed and holds can never be. The Yes/No buttons are the deterministic path.
- **Checking once a second** is simple and fast enough for a demo; no websockets.
- **Read-only shapes** (for the MCP tools; align with the data teammate): `get_summary` → `{ "balance": 3400.00, "account_name": "Checking", "spent_this_week": 109.55, "bills_due": [{ "biller_name": "Pepco", "amount": 600.00, "due_date": "2026-10-24" }] }`; `get_recent_purchases` → `[{ "merchant": "Giant", "amount": 86.40, "date": "2026-10-15" }]`. For `pay_bill`, if `amount` is omitted the backend fills it from the Nessie bill for that biller.
- **Failure wording:** MCP tools return a sentence ending "No money was moved." on any error, and the agent reads it. When a Yes/No tap fails, the app sends the agent the same kind of sentence with `sendContextualUpdate`.

## Left to the builder

- Exact animation of the pulsing rings and the idle/active transitions.
- Exact copy of status lines and agent prompts beyond what's quoted above.
- Component structure, state management, and styling approach inside the React app.
- Whether to show the transcript's in-progress (tentative) user text.

## Open items to confirm with teammates

- Voice teammate: enable MCP in the workspace, add the MCP server with tools auto-approved, Gemini as the LLM, public agent, "patient" turn setting, system prompt lines (read `spoken_message` verbatim; never say "sent" until told it executed; ask "anything else?" and end the call on no).
- Fraud teammate: hold every later request to a payee that was already held in the session; drop PIN release; add `confirmed`/`executed`/`cancelled` statuses and store the full request with the `transfer_id`; note that a $600 Pepco bill currently scores 25 → `allow` (no warning) because rules use overall average, not per-payee.
- Backend owner (unassigned): the MCP server and the endpoints above, transcript storage, CORS for the app, payee-name lookup.
