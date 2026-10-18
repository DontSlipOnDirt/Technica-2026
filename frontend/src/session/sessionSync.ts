// Keeps the screen and the backend in step while the agent's tools run on the MCP server.
// The app forwards what she says, checks for the current transfer, and handles Yes/No taps.

import { ApiError, type BankApi } from '../api/types'
import { screenReducer, type ScreenAction, type ScreenState } from './screenState'

const NO_MONEY_MOVED = 'No money was moved.'
const UNSURE = "I'm not sure that payment went through. Please check your balance before trying again."

function failure(err: unknown): string {
  const reason = err instanceof ApiError ? err.message : "I couldn't reach the bank."
  return `${reason} ${NO_MONEY_MOVED}`
}

/** Send one finished user line to the backend, so the fraud check sees her real words. */
export async function forwardUserLine(api: BankApi, state: ScreenState, text: string): Promise<void> {
  if (!state.conversation_id || !text.trim()) return
  try {
    await api.postTranscript(state.conversation_id, text)
  } catch {
    // A lost line shouldn't break the conversation; the next check still runs.
  }
}

/** Ask the backend for the current transfer and show it. On error the screen stays as it was. */
export async function checkCurrentTransfer(api: BankApi, dispatch: (a: ScreenAction) => void): Promise<void> {
  try {
    dispatch({ type: 'current', transfer: await api.getCurrentTransfer() })
  } catch {
    // Keep showing what we had; the next check will try again.
  }
}

/** Refresh after a tap and return the new state, or null if the bank couldn't be asked. */
async function refresh(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<ScreenState | null> {
  try {
    const action: ScreenAction = { type: 'current', transfer: await api.getCurrentTransfer() }
    dispatch(action)
    return screenReducer(state, action)
  } catch {
    return null
  }
}

function say(dispatch: (a: ScreenAction) => void, text: string): string {
  dispatch({ type: 'message', message: { role: 'agent', text } })
  return text
}

/**
 * After a failed tap, look again before claiming nothing moved: a lost response,
 * or the agent's voice yes, may already have sent it. If nobody can tell, say so.
 */
async function afterError(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void, err: unknown): Promise<string> {
  const after = await refresh(api, state, dispatch)
  const same = after?.transfer?.transfer_id === state.transfer?.transfer_id
  if (!after || (same && after.transfer?.status === 'unknown')) return say(dispatch, UNSURE)
  if (same && after.transfer?.status === 'executed') {
    return say(dispatch, `That payment was already sent. ${after.sentText ?? ''}`.trim())
  }
  return say(dispatch, failure(err))
}

/** A tap on a transfer that isn't waiting for a yes: describe where it really stands. */
function notWaiting(dispatch: (a: ScreenAction) => void, state: ScreenState): string {
  if (state.transfer?.status === 'executed') return say(dispatch, 'That payment was already sent.')
  if (state.transfer?.status === 'unknown') return say(dispatch, UNSURE)
  return say(dispatch, `That payment isn't waiting for a yes. ${NO_MONEY_MOVED}`)
}

/** The Yes button. Returns the sentence to tell the agent. */
export async function answerYes(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<string> {
  const t = state.transfer
  if (t?.status !== 'awaiting_yes') return notWaiting(dispatch, state)
  try {
    await api.confirmTransfer(t.transfer_id)
  } catch (err) {
    return afterError(api, state, dispatch, err)
  }
  const after = await refresh(api, state, dispatch)
  return `The customer tapped Yes. ${after?.sentText ?? 'The payment was sent.'}`
}

/** The No button. Returns the sentence to tell the agent. */
export async function answerNo(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<string> {
  const t = state.transfer
  if (t?.status !== 'awaiting_yes') return notWaiting(dispatch, state)
  try {
    await api.cancelTransfer(t.transfer_id)
  } catch (err) {
    return afterError(api, state, dispatch, err)
  }
  await refresh(api, state, dispatch)
  return `The customer tapped No. The payment was cancelled. ${NO_MONEY_MOVED}`
}
