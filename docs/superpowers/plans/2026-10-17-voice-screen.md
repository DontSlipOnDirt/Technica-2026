# Voice Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single Capital One voice screen (talking, Are-you-sure, sent, scam-caught) as a React app that runs against a stand-in API today and the team's real backend later.

**Architecture:** A Vite + React + TypeScript app in `frontend/`. Pure logic (API stand-in, screen-state reducer, ElevenLabs client tools) lives in small tested modules; React components only render state and forward taps. ElevenLabs runs in the browser through `@elevenlabs/react`; every money action goes through the `BankApi` interface, which is either the fake (default) or the real `/api/...` backend.

**Tech Stack:** Vite, React 18, TypeScript, Vitest, React Testing Library, `@elevenlabs/react`.

**Spec:** `docs/superpowers/specs/2026-10-17-voice-screen-design.md`

## Global Constraints

- All JSON field names are snake_case, exactly as in the spec's contract table.
- Money is dollars as decimal numbers; display as `$600.00` (two decimals, thousands separators: `$2,000.00`).
- Decisions are exactly `"allow"`, `"confirm"`, `"hold"`. Backend errors are `{"error": "message"}`.
- Every failure message the agent reads ends with the exact sentence `No money was moved.`
- A `hold` decision has no path to execution: no release button, no PIN, no confirm for a held `transfer_id`.
- No secret keys in the app. Only `VITE_ELEVENLABS_AGENT_ID`, `VITE_USE_FAKE_API`, and `VITE_API_BASE` env vars.
- Colors: navy `#013d5b`, Capital One red `#d03027`, Yes green `#1f8a3b`, warning bar `#fff6dd` with `#f2a900` left border.
- Font stack: `Optimist, "Helvetica Neue", Helvetica, Arial, sans-serif`.
- Yes/No buttons: stacked, full width, ~56px tall, 4px radius, 20px weight 600; labels exactly `✓ Yes, pay it` and `✕ No, cancel`.
- Scam box copy: heading `This looks like a scam`; body `We stopped your {amount} transfer. Your money has not moved.`; button `Call Capital One` as a `tel:` link.

## Review Focus

1. **Agent tries to confirm a held transfer** (or any id that isn't the one waiting for a yes) → refused with a "No money was moved." sentence; red box stays. Test in Task 4.
2. **Yes tapped twice fast, or tap + voice yes together** → exactly one payment. Tests in Task 2 (fake API idempotent) and Task 5 (button disabled while confirming).
3. **Backend unreachable / throws** → agent gets a sentence ending "No money was moved."; screen does not show Sent. Test in Task 4.
4. **She asks again for a held payee with innocent wording** ("just send fifty dollars to them") → held again. Test in Task 2.
5. **A new request while one is waiting for a yes** → the old one is cancelled and the panel shows the new one. Tests in Task 2 and Task 3.

---

## File Structure

```
frontend/
  index.html, package.json, vite.config.ts, tsconfig*.json   (Vite react-ts template)
  .env.example                       VITE_ELEVENLABS_AGENT_ID, VITE_USE_FAKE_API=true, VITE_API_BASE=
  public/capitalone-logo.svg         copied from .superpowers/brainstorm/1352-1792265007/content/
  src/
    main.tsx                         renders <VoiceScreen/>
    styles.css                       tokens + all component styles
    money.ts                         formatMoney
    api/types.ts                     contract types, ApiError, BankApi
    api/fakeApi.ts                   createFakeApi(): BankApi
    api/realApi.ts                   createRealApi(base): BankApi
    api/index.ts                     api: BankApi chosen by env
    session/screenState.ts           reducer + types
    session/clientTools.ts           makeClientTools(deps)
    session/useVoiceSession.ts       ElevenLabs wiring (manual test only)
    components/VoiceScreen.tsx       composes everything
    components/MicOrb.tsx, ConfirmPanel.tsx, SentBox.tsx, ScamBox.tsx, Chat.tsx
  src/**/*.test.ts(x)                next to the code they test
```

---

### Task 1: Scaffold the app, styles, logo, money formatting

**Files:**
- Create: `frontend/` from the Vite `react-ts` template, `frontend/.env.example`, `frontend/public/capitalone-logo.svg`, `frontend/src/styles.css`, `frontend/src/money.ts`
- Test: `frontend/src/money.test.ts`

**Interfaces:**
- Produces: `formatMoney(amount: number): string`; `npm test` runs Vitest (jsdom environment, `@testing-library/jest-dom` set up).

- [ ] **Step 1:** `npm create vite@latest frontend -- --template react-ts`, then in `frontend/`: `npm i @elevenlabs/react` and `npm i -D vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom`. Add `"test": "vitest run"` to scripts and `test: { environment: "jsdom", setupFiles: "./src/setupTests.ts" }` to `vite.config.ts` (setup file imports `@testing-library/jest-dom/vitest`). Delete the template's demo content and `App.css`.
- [ ] **Step 2:** Copy the logo SVG into `public/`. Write `.env.example` with the three vars from Global Constraints.
- [ ] **Step 3: Write the failing test** `money.test.ts`:

```ts
expect(formatMoney(600)).toBe("$600.00");
expect(formatMoney(2000)).toBe("$2,000.00");
expect(formatMoney(109.55)).toBe("$109.55");
```

- [ ] **Step 4:** Run `npm test` → FAIL (`formatMoney` not found).
- [ ] **Step 5:** Implement `formatMoney` with `Intl.NumberFormat("en-US", { style: "currency", currency: "USD" })`.
- [ ] **Step 6:** Run `npm test` → PASS. Run `npm run build` → succeeds.
- [ ] **Step 7:** Commit: `git add frontend && git commit -m "Scaffold voice screen app"`. Make sure `frontend/node_modules` and `frontend/dist` are git-ignored (template `.gitignore` does this).

### Task 2: Contract types and the stand-in API

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/api/fakeApi.ts`
- Test: `frontend/src/api/fakeApi.test.ts`

**Interfaces:**
- Produces (`types.ts`):

```ts
export type Decision = "allow" | "confirm" | "hold";
export type Kind = "transfer" | "bill";
export interface TransferRequestBody { kind: Kind; payee_name: string; amount: number | null; description: string; user_said: string; }
export interface FraudDecision { decision: Decision; risk_score: number; reasons: string[]; spoken_message: string; transfer_id: string; payee_name: string; amount: number; from_account_name: string; }
export interface Bill { biller_name: string; amount: number; due_date: string; }
export interface Summary { balance: number; account_name: string; spent_this_week: number; bills_due: Bill[]; }
export interface Purchase { merchant: string; amount: number; date: string; }
export class ApiError extends Error {}
export interface BankApi {
  requestTransfer(body: TransferRequestBody): Promise<FraudDecision>;
  confirmTransfer(transfer_id: string): Promise<{ status: "executed" }>;
  cancelTransfer(transfer_id: string): Promise<{ status: "cancelled" }>;
  getSummary(): Promise<Summary>;
  getPurchases(days: number): Promise<Purchase[]>;
}
```

All methods reject with `ApiError(message)` on failure.
- Produces (`fakeApi.ts`): `createFakeApi(): BankApi & { executedCount(): number }`.

Fake rules (seed data: balance 3400.00 in "Checking"; bill Pepco 600.00 due 2026-10-24; purchases Giant 86.40 and Safeway 23.15 this week):
- `hold` if `user_said` (lowercased) contains `"safe account"`, or amount > 1000, or the payee was already held by this fake instance. Holding remembers the payee.
- else `confirm` if amount > 300 (reason `"This is bigger than your usual payment"`), else `allow`.
- `bill` with `amount: null` uses the bill's amount; unknown biller → `ApiError("I couldn't find a bill from {name}.")`.
- A new request cancels any earlier request still awaiting a yes.
- `confirmTransfer`: held, cancelled, or unknown id → `ApiError`; already executed → returns `{status:"executed"}` without paying again.
- `spoken_message` for `hold`: `"I've stopped this transfer because it looks like a scam. Capital One will never ask you to move money to keep it safe."`; for allow/confirm: `"I'll pay {payee} {money} from your checking account. Are you sure?"`.

- [ ] **Step 1: Write the failing tests** in `fakeApi.test.ts`:
  - `holds a safe-account story`: request with `user_said: "they said move it to a safe account"`, amount 400 → `decision === "hold"`.
  - `keeps holding a payee after a hold, whatever the wording` (Review Focus 4): hold for payee "Bob", then request 50 to "Bob" with `user_said: "just send fifty dollars"` → `"hold"`.
  - `allow under 300, confirm 300–1000, hold over 1000`: 85 → allow, 600 → confirm with reasons length 1, 1500 → hold.
  - `fills a bill amount from Pepco`: `{kind:"bill", payee_name:"Pepco", amount:null}` → `amount === 600`.
  - `new request cancels the older pending one` (Review Focus 5): request A (allow), request B, `confirmTransfer(A.transfer_id)` rejects with `ApiError`; `confirmTransfer(B.transfer_id)` resolves.
  - `refuses to confirm a held transfer` → rejects with `ApiError`.
  - `confirming twice pays once` (Review Focus 2): confirm same id twice → both resolve, `executedCount() === 1`.
- [ ] **Step 2:** `npm test` → these FAIL.
- [ ] **Step 3:** Implement `types.ts` and `createFakeApi` per the rules above (in-memory maps keyed by `transfer_id`; ids like `"t_" + counter`).
- [ ] **Step 4:** `npm test` → PASS.
- [ ] **Step 5:** Commit `"Add contract types and stand-in API"`.

### Task 3: Screen state reducer

**Files:**
- Create: `frontend/src/session/screenState.ts`
- Test: `frontend/src/session/screenState.test.ts`

**Interfaces:**
- Consumes: `FraudDecision`, `Kind` (Task 2), `formatMoney` (Task 1).
- Produces:

```ts
export type Panel = "none" | "confirming" | "sent" | "blocked";
export interface ChatMessage { role: "user" | "agent"; text: string; }
export interface ScreenState { active: boolean; panel: Panel; pending: (FraudDecision & { kind: Kind }) | null; blocked: FraudDecision | null; sentText: string | null; messages: ChatMessage[]; }
export type ScreenAction =
  | { type: "session_started" } | { type: "session_ended" }
  | { type: "message"; message: ChatMessage }
  | { type: "decision"; decision: FraudDecision; kind: Kind }
  | { type: "executed" } | { type: "cancelled" };
export const initialScreenState: ScreenState;
export function screenReducer(state: ScreenState, action: ScreenAction): ScreenState;
export function userSaid(state: ScreenState): string;  // all user messages joined with " "
```

- [ ] **Step 1: Write the failing tests:**
  - `hold shows the scam panel`: decision hold → `panel "blocked"`, `blocked` set, `pending null`.
  - `allow and confirm show the Are-you-sure panel`: → `panel "confirming"`, `pending.transfer_id` matches.
  - `a new decision replaces the scam panel`: blocked, then an allow decision → `panel "confirming"`, `blocked null`.
  - `a new decision replaces the pending one` (Review Focus 5).
  - `executed shows sent copy`: bill Pepco 600 → `sentText === "Your Pepco bill of $600.00 has been sent."`; transfer to Maria 50 → `"$50.00 has been sent to Maria."`; `pending null`.
  - `cancelled clears the panel`: → `panel "none"`.
  - `session_ended keeps the scam panel`: blocked, then session_ended → `active false`, `panel "blocked"`.
  - `userSaid joins every user line, not just the last`: messages user "the bank said move it to a safe account", agent "...", user "nine hundred" → `"the bank said move it to a safe account nine hundred"`.
- [ ] **Step 2:** `npm test` → FAIL.
- [ ] **Step 3:** Implement the reducer.
- [ ] **Step 4:** `npm test` → PASS.
- [ ] **Step 5:** Commit `"Add screen state reducer"`.

### Task 4: ElevenLabs client tools

**Files:**
- Create: `frontend/src/session/clientTools.ts`
- Test: `frontend/src/session/clientTools.test.ts`

**Interfaces:**
- Consumes: `BankApi`, `ApiError` (Task 2); `ScreenAction`, `ScreenState` (Task 3); `formatMoney`.
- Produces:

```ts
export interface ToolDeps { api: BankApi; dispatch: (a: ScreenAction) => void; getState: () => ScreenState; }
export type ClientTools = {
  request_transfer(p: { payee_name: string; amount: number; memo?: string }): Promise<string>;
  pay_bill(p: { biller_name: string; amount?: number }): Promise<string>;
  confirm_payment(p: { transfer_id: string }): Promise<string>;
  cancel_payment(p: { transfer_id: string }): Promise<string>;
  get_summary(): Promise<string>;              // JSON.stringify(summary)
  get_recent_purchases(p: { days?: number }): Promise<string>;  // default 7, JSON string
};
export function makeClientTools(deps: ToolDeps): ClientTools;
```

Behavior: request/pay send `user_said: userSaid(getState())`, dispatch `decision`, return `spoken_message`. `confirm_payment` refuses (without calling the API) unless `transfer_id === getState().pending?.transfer_id`, returning `"That payment isn't waiting for a yes. No money was moved."`; on success dispatches `executed` and returns `"Done. " + sentText`. `cancel_payment` dispatches `cancelled`, returns `"Okay, I didn't send it."`. Any thrown error → returns `"{error message} No money was moved."` (non-ApiError → `"I couldn't reach the bank."`).

- [ ] **Step 1: Write the failing tests** (use `createFakeApi`, the real reducer, and a tiny store `let s = initialScreenState; dispatch = a => { s = screenReducer(s, a) }`):
  - `request_transfer sends the whole conversation as user_said`: messages already contain two user lines; spy on `api.requestTransfer` → called with `user_said` equal to both lines joined.
  - `request_transfer returns the spoken message and opens the panel`.
  - `refuses to confirm a held transfer` (Review Focus 1): after a hold, `confirm_payment({transfer_id: held.transfer_id})` → ends with `"No money was moved."`, `api.confirmTransfer` not called, `s.panel === "blocked"`.
  - `confirm after allow pays and shows sent`: returns string starting `"Done. "`, `s.panel === "sent"`.
  - `backend failure says no money moved` (Review Focus 3): api whose `confirmTransfer` rejects with `new TypeError("fetch failed")` → returns `"I couldn't reach the bank. No money was moved."`, `s.panel` still `"confirming"`.
- [ ] **Step 2:** `npm test` → FAIL.
- [ ] **Step 3:** Implement `makeClientTools`.
- [ ] **Step 4:** `npm test` → PASS.
- [ ] **Step 5:** Commit `"Add ElevenLabs client tools"`.

### Task 5: The screen components

**Files:**
- Create: `frontend/src/components/{VoiceScreen,MicOrb,ConfirmPanel,SentBox,ScamBox,Chat}.tsx`, fill `frontend/src/styles.css`, set `frontend/src/main.tsx` to render `<VoiceScreen/>`
- Test: `frontend/src/components/VoiceScreen.test.tsx`

**Interfaces:**
- Consumes: `ScreenState` (Task 3), `formatMoney`.
- Produces:

```ts
export interface VoiceScreenProps {
  state: ScreenState;
  onMicTap(): void;                 // start session if inactive, else end her turn
  onYes(): Promise<void>;
  onNo(): Promise<void>;
}
export function VoiceScreen(props: VoiceScreenProps): JSX.Element;
```

Layout and copy follow the spec's "one screen and its four looks" and the mockups `main-screens-v4.html` / `confirm-screens-v2.html` in `.superpowers/brainstorm/1352-1792265007/content/`. Header: logo `img` (`alt="Capital One"`) left, `Voice` right. MicOrb: pulsing rings when `active`, red shield when `panel === "blocked"`. Status line: `Tap to talk` (inactive), `Listening…` (active), `Say yes or no` (confirming), `Transfer stopped` (blocked). ConfirmPanel shows `Pay {payee} {money} from {from_account_name}?`, the reasons in the warning bar only when `decision === "confirm"`, and the two buttons. ScamBox lists `blocked.reasons`. Call number: copy Capital One's bank customer service number from https://www.capitalone.com/contact/ into a `CAPITAL_ONE_PHONE` constant in `ScamBox.tsx`.

- [ ] **Step 1: Write the failing tests** (render `VoiceScreen` with hand-built states):
  - `idle shows Tap to talk and the logo`.
  - `confirming shows the payment and both buttons`: text `Pay Pepco $600.00 from Checking?`, buttons named `✓ Yes, pay it` and `✕ No, cancel`.
  - `warning bar only for confirm`: reasons visible for `"confirm"`, absent for `"allow"`.
  - `Yes is disabled while confirming` (Review Focus 2): `onYes` returns a never-resolving promise; click Yes twice → `onYes` called once, button disabled.
  - `scam panel has no way through`: blocked state → heading `This looks like a scam`, text `We stopped your $2,000.00 transfer. Your money has not moved.`, a link named `Call Capital One` with `href` starting `tel:`; `queryByRole("button", { name: /yes|release|send/i })` is null.
  - `sent shows the sent text`.
- [ ] **Step 2:** `npm test` → FAIL.
- [ ] **Step 3:** Implement the components and styles (Global Constraints values).
- [ ] **Step 4:** `npm test` → PASS. `npm run dev` with a temporary hard-coded state in `main.tsx` to eyeball each look at 375px wide against the mockups, then put `main.tsx` back.
- [ ] **Step 5:** Commit `"Add voice screen components"`.

### Task 6: Wire ElevenLabs and the API choice

**Files:**
- Create: `frontend/src/api/realApi.ts`, `frontend/src/api/index.ts`, `frontend/src/session/useVoiceSession.ts`
- Modify: `frontend/src/main.tsx`
- Test: `frontend/src/api/realApi.test.ts`

**Interfaces:**
- Consumes: everything above.
- Produces: `createRealApi(base: string): BankApi` (POST/GET to `${base}/api/transfer/request|confirm|cancel`, `/api/summary`, `/api/purchases?days=N`; non-2xx → `ApiError(body.error)`); `api: BankApi` in `api/index.ts` (fake unless `VITE_USE_FAKE_API === "false"`); `useVoiceSession(api: BankApi): VoiceScreenProps`.

`useVoiceSession`: `useReducer(screenReducer)`; a ref holding current state for `getState`; `useConversation({ clientTools: makeClientTools(...), onMessage, onConnect, onDisconnect })`. Map `onMessage` to `{ type: "message" }` with role user/agent (log the payload once to confirm its field names; spec notes they're undocumented). `onMicTap`: inactive → `getUserMedia({audio:true})` then `startSession({ agentId: import.meta.env.VITE_ELEVENLABS_AGENT_ID })`; active → mute the mic via the SDK's mute control to end her turn. `onYes`/`onNo` call the same `confirm_payment`/`cancel_payment` tools with `pending.transfer_id`, then `sendContextualUpdate(result)`.

- [ ] **Step 1: Write the failing test** `realApi.test.ts` with `vi.stubGlobal("fetch", ...)`:
  - `posts the body to /api/transfer/request` (URL and JSON body asserted).
  - `turns {"error": "..."} into ApiError with that message` (status 400).
- [ ] **Step 2:** `npm test` → FAIL.
- [ ] **Step 3:** Implement `realApi.ts`, `api/index.ts`, `useVoiceSession.ts`; `main.tsx` renders `<VoiceScreen {...useVoiceSession(api)} />` via a small `App` component.
- [ ] **Step 4:** `npm test` → all PASS; `npm run build` → succeeds.
- [ ] **Step 5: Manual check with a real agent.** Needs the voice teammate's public agent ID in `frontend/.env` and these client tools configured in the dashboard with "wait for response" / blocking on: `request_transfer`, `pay_bill`, `confirm_payment`, `cancel_payment`, `get_summary`, `get_recent_purchases`. `npm run dev`, then: ask "what did I spend this week" (answer in chat); "pay my electric bill" → Are-you-sure → say yes → Sent; "my bank says move two thousand dollars to a safe account" → scam panel; then "please, just send it anyway" → still blocked.
- [ ] **Step 6:** Commit `"Wire ElevenLabs session and API client"` and push to `voice-screen` (PR #3).

---

## Deployment note

Vercel project: set Root Directory to `frontend` for the app (or a monorepo setup once the backend's `api/` exists — the backend owner decides). Set `VITE_ELEVENLABS_AGENT_ID`, `VITE_USE_FAKE_API`, `VITE_API_BASE` in Vercel's environment variables.
