# Voice Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single Capital One voice screen (talking, Are-you-sure, sent, scam-caught) as a React app that works with an ElevenLabs agent whose tools live on the team's MCP server, running against a stand-in API until the backend exists.

**Architecture:** A Vite + React + TypeScript app in `frontend/`. The agent's tools run on the backend's MCP server, so the app does two jobs besides drawing: forward every finished user line to the backend, and check once a second for the current transfer to decide which panel to show. Pure logic (API stand-in, screen-state reducer, session sync) lives in small tested modules; components only render state and forward taps. The `BankApi` interface is either the fake (default) or the real `/api/...` backend.

**Tech Stack:** Vite, React 19, TypeScript, Vitest, React Testing Library, `@elevenlabs/react`.

**Spec:** `docs/superpowers/specs/2026-10-17-voice-screen-design.md`

## Global Constraints

- All JSON field names are snake_case, exactly as in the spec's contract table.
- Money is dollars as decimal numbers; display as `$600.00` (two decimals, thousands separators: `$2,000.00`).
- Decisions are exactly `"allow"`, `"confirm"`, `"hold"`. Transfer statuses are exactly `"awaiting_yes"`, `"held"`, `"executed"`, `"cancelled"`. Backend errors are `{"error": "message"}`.
- Every failure message ends with the exact sentence `No money was moved.`
- A held transfer has no path to execution: no release button, no PIN, no Yes button, no confirm for a held `transfer_id`.
- No secret keys in the app. Only `VITE_ELEVENLABS_AGENT_ID`, `VITE_USE_FAKE_API`, and `VITE_API_BASE` env vars.
- Check for the current transfer every 1000 ms while a session is active.
- Colors: navy `#013d5b`, Capital One red `#d03027`, Yes green `#1f8a3b`, warning bar `#fff6dd` with `#f2a900` left border.
- Font stack: `Optimist, "Helvetica Neue", Helvetica, Arial, sans-serif`.
- Yes/No buttons: stacked, full width, ~56px tall, 4px radius, 20px weight 600; labels exactly `✓ Yes, pay it` and `✕ No, cancel`.
- Scam box copy: heading `This looks like a scam`; body `We stopped your {amount} transfer. Your money has not moved.`; button `Call Capital One` as a `tel:` link.

## Review Focus

1. **Yes tapped on a transfer that is no longer awaiting a yes** (held, cancelled, replaced) → refused without calling the backend, "No money was moved." Test in Task 4.
2. **Yes tapped twice fast, or tap + voice yes together** → exactly one payment. Tests in Task 2 (fake confirm idempotent) and Task 5 (button disabled while confirming).
3. **Backend unreachable when tapping Yes or while checking** → "No money was moved." for the tap; a failed check leaves the screen as it was instead of blanking it. Tests in Task 4.
4. **She asks again for a held payee with innocent wording** → held again (scam words from earlier turns still count). Test in Task 2.
5. **A new request while one is waiting for a yes** → the old one is cancelled and the panel shows the new one. Tests in Task 2 and Task 3.

---

## File Structure

```
frontend/
  index.html, package.json, vite.config.ts, tsconfig*.json   (Vite react-ts template)
  .env.example                       VITE_ELEVENLABS_AGENT_ID, VITE_USE_FAKE_API=true, VITE_API_BASE=
  public/capitalone-logo.svg         copied from .superpowers/brainstorm/1352-1792265007/content/
  src/
    main.tsx                         renders <App/>
    setupTests.ts                    jest-dom for Vitest
    styles.css                       tokens + all component styles
    money.ts                         formatMoney
    api/types.ts                     contract types, ApiError, BankApi
    api/fakeApi.ts                   createFakeApi(): FakeBankApi
    api/realApi.ts                   createRealApi(base): BankApi
    api/index.ts                     api: BankApi chosen by env
    session/screenState.ts           reducer + types
    session/sessionSync.ts           forwardUserLine, checkCurrentTransfer, answerYes, answerNo
    session/useVoiceSession.ts       ElevenLabs + polling wiring (manual test only)
    components/VoiceScreen.tsx       composes everything
    components/MicOrb.tsx, ConfirmPanel.tsx, SentBox.tsx, ScamBox.tsx, Chat.tsx
    App.tsx                          <VoiceScreen {...useVoiceSession(api)} />
  src/**/*.test.ts(x)                next to the code they test
```

The MCP server itself is backend work (owner unassigned) and is not in this plan.

---

### Task 1: Scaffold the app, styles, logo, money formatting

**Files:**
- Create: `frontend/` from the Vite `react-ts` template, `frontend/.env.example`, `frontend/public/capitalone-logo.svg`, `frontend/src/setupTests.ts`, `frontend/src/styles.css`, `frontend/src/money.ts`
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

- [ ] **Step 4:** Run `npm test`. Expected: FAIL (`formatMoney` not found).
- [ ] **Step 5:** Implement `formatMoney` with `Intl.NumberFormat("en-US", { style: "currency", currency: "USD" })`.
- [ ] **Step 6:** Run `npm test`. Expected: PASS. Run `npm run build`. Expected: succeeds.
- [ ] **Step 7:** Commit `"Scaffold voice screen app"`. `frontend/node_modules` and `frontend/dist` must be git-ignored (template `.gitignore`).

### Task 2: Contract types and the stand-in API

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/api/fakeApi.ts`
- Test: `frontend/src/api/fakeApi.test.ts`

**Interfaces:**
- Produces (`types.ts`):

```ts
export type Decision = "allow" | "confirm" | "hold";
export type Kind = "transfer" | "bill";
export type TransferStatus = "awaiting_yes" | "held" | "executed" | "cancelled";
export interface CurrentTransfer { transfer_id: string; kind: Kind; status: TransferStatus; decision: Decision; risk_score: number; reasons: string[]; spoken_message: string; payee_name: string; amount: number; from_account_name: string; }
export class ApiError extends Error {}
export interface BankApi {
  postTranscript(conversation_id: string, text: string): Promise<void>;
  getCurrentTransfer(): Promise<CurrentTransfer | null>;
  confirmTransfer(transfer_id: string): Promise<{ status: "executed" }>;
  cancelTransfer(transfer_id: string): Promise<{ status: "cancelled" }>;
}
```

All methods reject with `ApiError(message)` on failure.
- Produces (`fakeApi.ts`):

```ts
export interface SimulatedRequest { kind: Kind; payee_name: string; amount: number | null; }
export interface FakeBankApi extends BankApi {
  simulateRequest(req: SimulatedRequest): Promise<CurrentTransfer>;  // plays the MCP server's request_transfer / pay_bill
  executedCount(): number;
}
export function createFakeApi(): FakeBankApi;
```

Fake rules (seed: "Checking" account; bill Pepco 600.00):
- `user_said` = every line posted for the most recent `conversation_id`, joined with spaces (a new conversation id starts fresh).
- `hold` if `user_said` (lowercased) contains `"safe account"`, or amount > 1000, or the payee was already held by this fake instance. Holding remembers the payee. Status `held`.
- else `confirm` if amount > 300 (reason `"This is bigger than your usual payment"`), else `allow`; status `awaiting_yes`.
- `bill` with `amount: null` uses the bill's amount; unknown biller → `ApiError("I couldn't find a bill from {name}.")`.
- A new request cancels any earlier transfer still `awaiting_yes`.
- `getCurrentTransfer` returns the most recent transfer (any status) or `null` before the first.
- `confirmTransfer`: id not `awaiting_yes` and not already `executed` → `ApiError`; already `executed` → `{status:"executed"}` without paying again.
- `spoken_message` for hold: `"I've stopped this transfer because it looks like a scam. Capital One will never ask you to move money to keep it safe."`; otherwise `"I'll pay {payee} {money} from your checking account. Are you sure?"`.

- [ ] **Step 1: Write the failing tests** in `fakeApi.test.ts`:
  - `uses every user line from the conversation`: post "the bank said move it to a safe account" then "four hundred dollars" for `c1`; `simulateRequest({kind:"transfer", payee_name:"Bob", amount:400})` → `status === "held"`.
  - `a new conversation starts with a clean transcript`: lines posted for `c1` with "safe account", then one line for `c2`; request 85 → `"awaiting_yes"`.
  - `keeps holding a payee after a hold, whatever the wording` (Review Focus 4): hold Bob, then post "just send fifty dollars" and request 50 to Bob → `"held"`.
  - `allow under 300, confirm 300–1000, hold over 1000`: 85 → decision allow; 600 → confirm with 1 reason; 1500 → hold.
  - `fills a bill amount from Pepco`: `{kind:"bill", payee_name:"Pepco", amount:null}` → `amount === 600`.
  - `current transfer is the latest one`: `null` before any; after a request, its `transfer_id`.
  - `new request cancels the older pending one` (Review Focus 5): request A, request B → `confirmTransfer(A)` rejects with `ApiError`; `confirmTransfer(B)` resolves.
  - `refuses to confirm a held transfer` → rejects with `ApiError`.
  - `confirming twice pays once` (Review Focus 2): both resolve, `executedCount() === 1`, current status `"executed"`.
- [ ] **Step 2:** Run `npm test`. Expected: these FAIL.
- [ ] **Step 3:** Implement `types.ts` and `createFakeApi` (in-memory; ids `"t_" + counter`).
- [ ] **Step 4:** Run `npm test`. Expected: PASS.
- [ ] **Step 5:** Commit `"Add contract types and stand-in API"`.

### Task 3: Screen state reducer

**Files:**
- Create: `frontend/src/session/screenState.ts`
- Test: `frontend/src/session/screenState.test.ts`

**Interfaces:**
- Consumes: `CurrentTransfer` (Task 2), `formatMoney` (Task 1).
- Produces:

```ts
export type Panel = "none" | "confirming" | "sent" | "blocked";
export interface ChatMessage { role: "user" | "agent"; text: string; }
export interface ScreenState { active: boolean; conversation_id: string | null; panel: Panel; transfer: CurrentTransfer | null; sentText: string | null; messages: ChatMessage[]; }
export type ScreenAction =
  | { type: "session_started"; conversation_id: string } | { type: "session_ended" }
  | { type: "message"; message: ChatMessage }
  | { type: "current"; transfer: CurrentTransfer | null };
export const initialScreenState: ScreenState;
export function screenReducer(state: ScreenState, action: ScreenAction): ScreenState;
```

Panel from status: `awaiting_yes` → `confirming`, `held` → `blocked`, `executed` → `sent`, `cancelled` → `none`. `current` with `null` leaves the state unchanged. `current` with an identical `transfer_id` and `status` returns the same state object (no re-render churn).

- [ ] **Step 1: Write the failing tests:**
  - `held shows the scam panel`.
  - `awaiting_yes shows the Are-you-sure panel` with `transfer.transfer_id` matching.
  - `a new transfer replaces the scam panel`: held t_1, then awaiting_yes t_2 → `panel "confirming"`.
  - `a new transfer replaces the pending one` (Review Focus 5): awaiting t_1, then awaiting t_2 → `transfer.transfer_id === "t_2"`.
  - `executed shows sent copy`: bill Pepco 600 → `sentText === "Your Pepco bill of $600.00 has been sent."`; transfer to Maria 50 → `"$50.00 has been sent to Maria."`.
  - `cancelled clears the panel` → `panel "none"`.
  - `null leaves the screen as it was`.
  - `same transfer and status returns the same state object` (`toBe`).
  - `session_ended keeps the scam panel`: held, then session_ended → `active false`, `panel "blocked"`.
  - `messages append in order`.
- [ ] **Step 2:** Run `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement the reducer.
- [ ] **Step 4:** Run `npm test`. Expected: PASS.
- [ ] **Step 5:** Commit `"Add screen state reducer"`.

### Task 4: Session sync (transcript forwarding, checking, Yes/No)

**Files:**
- Create: `frontend/src/session/sessionSync.ts`
- Test: `frontend/src/session/sessionSync.test.ts`

**Interfaces:**
- Consumes: `BankApi`, `ApiError` (Task 2); `ScreenState`, `ScreenAction`, `screenReducer` (Task 3).
- Produces:

```ts
export function forwardUserLine(api: BankApi, state: ScreenState, text: string): Promise<void>;   // no-op without conversation_id or for blank text; swallows errors
export function checkCurrentTransfer(api: BankApi, dispatch: (a: ScreenAction) => void): Promise<void>;  // on error: dispatch nothing
export function answerYes(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<string>;
export function answerNo(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<string>;
```

`answerYes`: refuses without calling the API unless `state.transfer?.status === "awaiting_yes"`, returning `"That payment isn't waiting for a yes. No money was moved."`; on success calls `checkCurrentTransfer` and returns `"The customer tapped Yes. " + sentText` (sentText from the dispatched state, or `"The payment was sent."`). `answerNo`: same guard; on success checks and returns `"The customer tapped No. The payment was cancelled. No money was moved."`. Errors: `ApiError` → `"{message} No money was moved."`; anything else → `"I couldn't reach the bank. No money was moved."`. The returned string is what the app passes to `sendContextualUpdate`.

- [ ] **Step 1: Write the failing tests** (fake API + real reducer in a tiny store `let s = ...; const dispatch = (a) => { s = screenReducer(s, a) }`):
  - `forwards a user line under the conversation id`: spy `api.postTranscript` → called with `("c1", "hello")`.
  - `does not forward before a session starts or for blank text`.
  - `checking shows the latest transfer`: `simulateRequest` 85 → after `checkCurrentTransfer`, `s.panel === "confirming"`.
  - `a failed check leaves the screen as it was` (Review Focus 3): api whose `getCurrentTransfer` rejects → panel unchanged.
  - `Yes pays and shows sent`: returns string starting `"The customer tapped Yes. "`, `s.panel === "sent"`.
  - `Yes on a held transfer is refused without calling the bank` (Review Focus 1): spy `confirmTransfer` not called, result ends `"No money was moved."`, `s.panel === "blocked"`.
  - `Yes when the bank is unreachable says no money moved` (Review Focus 3): `confirmTransfer` rejects with `new TypeError("fetch failed")` → `"I couldn't reach the bank. No money was moved."`, `s.panel` still `"confirming"`.
  - `No cancels`: `s.panel === "none"`, result ends `"No money was moved."`.
- [ ] **Step 2:** Run `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement `sessionSync.ts`.
- [ ] **Step 4:** Run `npm test`. Expected: PASS.
- [ ] **Step 5:** Commit `"Add session sync for MCP flow"`.

### Task 5: The screen components

**Files:**
- Create: `frontend/src/components/{VoiceScreen,MicOrb,ConfirmPanel,SentBox,ScamBox,Chat}.tsx`, fill `frontend/src/styles.css`
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

Layout and copy follow the spec's "one screen and its four looks" and the mockups `main-screens-v4.html` / `confirm-screens-v2.html` in `.superpowers/brainstorm/1352-1792265007/content/`. Header: logo `img` (`alt="Capital One"`) left, `Voice` right. MicOrb is a button (`aria-label` `Talk` when inactive, `Done talking` when active): pulsing rings when `active`, red shield when `panel === "blocked"`. Status line: `Tap to talk` (inactive), `Listening…` (active), `Say yes or no` (confirming), `Transfer stopped` (blocked). ConfirmPanel shows `Pay {payee} {money} from {from_account_name}?`, the reasons in the warning bar only when `decision === "confirm"`, and the two buttons. ScamBox lists `transfer.reasons`. Call number: copy Capital One's bank customer service number from https://www.capitalone.com/contact/ into a `CAPITAL_ONE_PHONE` constant in `ScamBox.tsx`.

- [ ] **Step 1: Write the failing tests** (render `VoiceScreen` with hand-built states):
  - `idle shows Tap to talk and the logo`.
  - `confirming shows the payment and both buttons`: text `Pay Pepco $600.00 from Checking?`, buttons named `✓ Yes, pay it` and `✕ No, cancel`.
  - `warning bar only for confirm`: reasons visible for `"confirm"`, absent for `"allow"`.
  - `Yes is disabled while confirming` (Review Focus 2): `onYes` returns a never-resolving promise; click Yes twice → `onYes` called once, both buttons disabled.
  - `scam panel has no way through`: held state → heading `This looks like a scam`, text `We stopped your $2,000.00 transfer. Your money has not moved.`, a link named `Call Capital One` with `href` starting `tel:`; `queryByRole("button", { name: /yes|release|send/i })` is null.
  - `sent shows the sent text`.
  - `chat shows both sides`.
- [ ] **Step 2:** Run `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement the components and styles (Global Constraints values).
- [ ] **Step 4:** Run `npm test`. Expected: PASS. Eyeball each look at 375px wide against the mockups with `npm run dev`.
- [ ] **Step 5:** Commit `"Add voice screen components"`.

### Task 6: Wire ElevenLabs, checking, and the API choice

**Files:**
- Create: `frontend/src/api/realApi.ts`, `frontend/src/api/index.ts`, `frontend/src/session/useVoiceSession.ts`, `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Test: `frontend/src/api/realApi.test.ts`

**Interfaces:**
- Consumes: everything above.
- Produces: `createRealApi(base: string): BankApi` (`POST ${base}/api/transcript`, `GET ${base}/api/transfer/current` unwrapping `{transfer}`, `POST ${base}/api/transfer/confirm|cancel`; non-2xx → `ApiError(body.error)`); `api: BankApi` in `api/index.ts` (fake unless `VITE_USE_FAKE_API === "false"`; in fake mode also set `window.fakeApi` so `simulateRequest` can be called from the browser console to demo without ElevenLabs); `useVoiceSession(api: BankApi): VoiceScreenProps`.

`useVoiceSession`: `useReducer(screenReducer)` plus a ref holding current state; `useConversation({ onMessage, onConnect, onDisconnect })` with **no client tools**. `onMessage`: append to chat; for final user lines also `forwardUserLine` (log the payload once to confirm its field names; the spec notes they're undocumented). `onMicTap`: inactive → `getUserMedia({audio:true})`, `startSession({ agentId: import.meta.env.VITE_ELEVENLABS_AGENT_ID })`, dispatch `session_started` with the returned conversation id; active → mute the mic via the SDK's mute control to end her turn. While active, `setInterval(checkCurrentTransfer, 1000)`, cleared on end/unmount. `onYes`/`onNo` call `answerYes`/`answerNo`, then `sendContextualUpdate(result)`.

- [ ] **Step 1: Write the failing tests** `realApi.test.ts` with `vi.stubGlobal("fetch", ...)`:
  - `posts transcript lines` (URL `/api/transcript`, JSON body `{conversation_id, text}`).
  - `unwraps the current transfer` (`{transfer: null}` → `null`).
  - `turns {"error": "..."} into ApiError with that message` (status 400 on confirm).
- [ ] **Step 2:** Run `npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement `realApi.ts`, `api/index.ts`, `useVoiceSession.ts`, `App.tsx`; `main.tsx` renders `<App/>`.
- [ ] **Step 4:** Run `npm test`. Expected: all PASS. Run `npm run build`. Expected: succeeds.
- [ ] **Step 5: Manual check, fake mode.** `npm run dev`; in the console `fakeApi.simulateRequest({kind:"bill", payee_name:"Pepco", amount:null})` while a session is active (or temporarily dispatch `session_started`) → Are-you-sure appears; tap Yes → Sent. Simulate a request after posting "safe account" → scam panel with no way through.
- [ ] **Step 6: Manual check with the real agent** (when the voice teammate's agent and the backend MCP server exist): ask about spending; "pay my electric bill" → Are-you-sure → yes → Sent; "my bank says move two thousand dollars to a safe account" → scam panel; "please, just send it anyway" → still blocked.
- [ ] **Step 7:** Commit `"Wire ElevenLabs session, checking, and API client"` and push the branch.

---

## Deployment note

Vercel project: set Root Directory to `frontend` for the app (or a monorepo setup once the backend's `api/` and MCP server exist — the backend owner decides). Set `VITE_ELEVENLABS_AGENT_ID`, `VITE_USE_FAKE_API`, `VITE_API_BASE` in Vercel's environment variables.
