// Everything the screen shows, as one state object, and how it changes.

import type { CurrentTransfer, TransferStatus } from '../api/types'
import { formatMoney } from '../money'

export type Panel = 'none' | 'confirming' | 'sent' | 'blocked'

export interface ChatMessage {
  role: 'user' | 'agent'
  text: string
}

export interface ScreenState {
  active: boolean
  conversation_id: string | null
  panel: Panel
  transfer: CurrentTransfer | null
  sentText: string | null
  messages: ChatMessage[]
}

export type ScreenAction =
  | { type: 'session_started'; conversation_id: string }
  | { type: 'session_ended' }
  | { type: 'message'; message: ChatMessage }
  | { type: 'current'; transfer: CurrentTransfer | null }

export const initialScreenState: ScreenState = {
  active: false,
  conversation_id: null,
  panel: 'none',
  transfer: null,
  sentText: null,
  messages: [],
}

const PANEL_FOR_STATUS: Record<TransferStatus, Panel> = {
  awaiting_yes: 'confirming',
  held: 'blocked',
  executed: 'sent',
  cancelled: 'none',
}

function sentText(t: CurrentTransfer): string {
  const money = formatMoney(t.amount)
  return t.kind === 'bill'
    ? `Your ${t.payee_name} bill of ${money} has been sent.`
    : `${money} has been sent to ${t.payee_name}.`
}

export function screenReducer(state: ScreenState, action: ScreenAction): ScreenState {
  switch (action.type) {
    case 'session_started':
      return { ...state, active: true, conversation_id: action.conversation_id }
    case 'session_ended':
      return { ...state, active: false }
    case 'message':
      return { ...state, messages: [...state.messages, action.message] }
    case 'current': {
      const t = action.transfer
      // Nothing new from the backend (or a failed check): keep the screen as it is.
      if (!t) return state
      if (state.transfer?.transfer_id === t.transfer_id && state.transfer.status === t.status) return state
      return {
        ...state,
        transfer: t,
        panel: PANEL_FOR_STATUS[t.status],
        sentText: t.status === 'executed' ? sentText(t) : null,
      }
    }
  }
}
