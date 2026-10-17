// Keeps the screen and the backend in step while the agent's tools run on the MCP server.
// The app forwards what she says, checks for the current transfer, and handles Yes/No taps.

import { ApiError, type BankApi } from '../api/types'
import { screenReducer, type ScreenAction, type ScreenState } from './screenState'

const NO_MONEY_MOVED = 'No money was moved.'

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

/** Refresh after a tap and return the new state, so the caller can describe it. */
async function refresh(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<ScreenState> {
  try {
    const action: ScreenAction = { type: 'current', transfer: await api.getCurrentTransfer() }
    dispatch(action)
    return screenReducer(state, action)
  } catch {
    return state
  }
}

/** The Yes button. Returns the sentence to tell the agent. */
export async function answerYes(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<string> {
  const t = state.transfer
  if (t?.status !== 'awaiting_yes') return `That payment isn't waiting for a yes. ${NO_MONEY_MOVED}`
  try {
    await api.confirmTransfer(t.transfer_id)
  } catch (err) {
    return failure(err)
  }
  const after = await refresh(api, state, dispatch)
  return `The customer tapped Yes. ${after.sentText ?? 'The payment was sent.'}`
}

/** The No button. Returns the sentence to tell the agent. */
export async function answerNo(api: BankApi, state: ScreenState, dispatch: (a: ScreenAction) => void): Promise<string> {
  const t = state.transfer
  if (t?.status !== 'awaiting_yes') return `That payment isn't waiting for a yes. ${NO_MONEY_MOVED}`
  try {
    await api.cancelTransfer(t.transfer_id)
  } catch (err) {
    return failure(err)
  }
  await refresh(api, state, dispatch)
  return `The customer tapped No. The payment was cancelled. ${NO_MONEY_MOVED}`
}
