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
- The agent's own wording of the request being what the fraud check scans, instead of what the customer actually said.
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
- Tapping the circle while she is talking ends her turn immediately. Otherwise ElevenLabs decides when her turn is over.
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

### Failures
- Any failure (backend down, Nessie error, insufficient funds, payee not found) shows a chat message ending in the standard sentence **"No money was moved."**

## How it works (the parts decided)

- **Voice:** ElevenLabs Agents, run in the browser with `@elevenlabs/react` (`useConversation`). The voice teammate configures the agent in the ElevenLabs dashboard and chooses a Gemini model as its LLM there. The agent is public so the app needs only the agent ID, never an ElevenLabs key.
- **Money tools are client tools.** `request_transfer` and `pay_bill` run in the app, not on a server. When the agent calls one, the app sends the backend the agent's fields **plus the customer's own words from the transcript as `user_said`**. In the ElevenLabs dashboard these tools must be set to block the conversation (wait for the result).
- **Tools take names, not IDs.** `request_transfer(payee_name, amount, memo)` and `pay_bill(biller_name, amount?)`. The backend looks up the Nessie account ID.
- **Pending action by ID.** The backend's request endpoint returns the fraud decision with a `transfer_id`. Yes (voice or tap) confirms by that ID only; the backend sends exactly what it stored. A new money request cancels any older pending one. Confirming the same ID twice must not pay twice.
- **Voice yes:** the agent calls a `confirm_payment(transfer_id)` / `cancel_payment(transfer_id)` client tool; the Yes/No buttons call the same app functions. Prompt rule for the agent: only a clear yes counts; if unsure, ask again.
- **Read vs write is structural:** read tools return data; write tools can only create a pending action. There is no tool that moves money directly.
- **Turn-taking:** deferred to ElevenLabs (e.g. its "patient" setting). Tap-the-circle-to-finish is the explicit override.
- **After a tap or voice yes,** the app tells the agent the outcome (`sendContextualUpdate`) so it can say "Done" and ask if there's anything else.
- **Stack:** React + Vite in `frontend/`, deployed to Vercel in the same project as the Python `api/` functions. Brand navy `#013d5b`, red `#d03027`.
- **Stand-in API:** until the backend exists, a fake API in the app returns made-up data in the agreed shapes (e.g. `hold` when the request mentions "safe account" or is over $1,000; `confirm` between $300 and $1,000; `allow` otherwise), so the app is never blocked on teammates.

## Backend contract the screen depends on

Owned by teammates; listed so the app and backend agree. All JSON is snake_case, money is dollars as decimals, dates `2026-10-17T14:32:00`, errors `{"error": "message"}`.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/transfer/request` | `kind` (`"transfer"`/`"bill"`), `payee_name`, `amount`, `description`, `user_said` | `decision`, `risk_score`, `reasons`, `spoken_message`, `transfer_id`, plus `payee_name`, `amount`, `from_account_name` for display |
| `POST /api/transfer/confirm` | `transfer_id` | `status: "executed"` or `{"error": ...}` |
| `POST /api/transfer/cancel` | `transfer_id` | `status: "cancelled"` |
| `GET /api/summary` | — | summary numbers for read-only answers |

`POST /transfer/release` and `GET /alerts` from the original contract are not used by this build.

## Calls made by Claude (check these)

- **`user_said` = every final user line in the session so far**, joined with spaces, not just the last turn. Scam coaching often comes several turns before the amount ("the bank said move it to a safe account" … "nine hundred dollars").
- **No app-side "did she really say yes" classifier.** Voice yes relies on the agent's prompt rule; the real protection is that only fraud-approved pending actions can be confirmed and holds can never be. The Yes/No buttons are the deterministic path.
- **Read-only stand-in shapes** (to align with the data teammate): `GET /api/summary` → `{ "balance": 3400.00, "account_name": "Checking", "spent_this_week": 109.55, "bills_due": [{ "biller_name": "Pepco", "amount": 600.00, "due_date": "2026-10-24" }] }`; `GET /api/purchases?days=7` → `[{ "merchant": "Giant", "amount": 86.40, "date": "2026-10-15" }]`. For `pay_bill`, if `amount` is omitted the backend fills it from the Nessie bill for that biller.
- **Failure wording comes from the app's tool result.** When an endpoint returns `{"error": ...}`, the client tool returns a sentence ending "No money was moved." and the agent reads it; the transcript stays a view of ElevenLabs' messages only.

## Left to the builder

- Exact animation of the pulsing rings and the idle/active transitions.
- Exact copy of status lines and agent prompts beyond what's quoted above.
- How read-only tools (`get_summary`, `get_recent_purchases`) are wired (client or server tool) — whichever is simpler with the stand-in API.
- Component structure, state management, and styling approach inside the React app.
- Whether to show the transcript's in-progress (tentative) user text.

## Open items to confirm with teammates

- Voice teammate: tool names/params above, blocking client tools, Gemini as the LLM, public agent, "patient" turn setting, system prompt lines (read `spoken_message` verbatim; never say "sent" until told it executed; ask "anything else?" and end the call on no).
- Fraud teammate: drop PIN release; add `confirmed`/`executed`/`cancelled` statuses and store the full request with the `transfer_id`; note that a $600 Pepco bill currently scores 25 → `allow` (no warning) because rules use overall average, not per-payee.
- Backend owner (unassigned): the endpoints above, CORS for the app, payee-name lookup.
