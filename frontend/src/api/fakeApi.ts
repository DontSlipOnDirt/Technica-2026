// Stand-in for the backend so the app can be built and demoed before the real one exists.
// simulateRequest plays the MCP server's request_transfer / pay_bill tools.

import { formatMoney } from '../money'
import { ApiError, type BankApi, type CurrentTransfer, type Kind } from './types'

export interface SimulatedRequest {
  kind: Kind
  payee_name: string
  amount: number | null
}

export interface FakeBankApi extends BankApi {
  simulateRequest(req: SimulatedRequest): Promise<CurrentTransfer>
  executedCount(): number
}

const ACCOUNT_NAME = 'Checking'
const BILLS: Record<string, number> = { pepco: 600 }
const CONFIRM_OVER = 300
const HOLD_OVER = 1000

const HOLD_MESSAGE =
  "I've stopped this transfer because it looks like a scam. " +
  'Capital One will never ask you to move money to keep it safe.'

export function createFakeApi(): FakeBankApi {
  let conversationId: string | null = null
  let lines: string[] = []
  let counter = 0
  let current: CurrentTransfer | null = null
  let executed = 0
  const transfers = new Map<string, CurrentTransfer>()
  const heldPayees = new Set<string>()

  function find(transfer_id: string): CurrentTransfer {
    const t = transfers.get(transfer_id)
    if (!t) throw new ApiError("I couldn't find that payment.")
    return t
  }

  return {
    async postTranscript(conversation_id, text) {
      if (conversation_id !== conversationId) {
        conversationId = conversation_id
        lines = []
      }
      lines.push(text)
    },

    async getCurrentTransfer() {
      return current ? { ...current } : null
    },

    async confirmTransfer(transfer_id) {
      const t = find(transfer_id)
      if (t.status === 'executed') return { status: 'executed' }
      if (t.status !== 'awaiting_yes') throw new ApiError("That payment can't be sent.")
      t.status = 'executed'
      executed += 1
      return { status: 'executed' }
    },

    async cancelTransfer(transfer_id) {
      const t = find(transfer_id)
      if (t.status === 'executed') throw new ApiError('That payment was already sent.')
      if (t.status === 'awaiting_yes') t.status = 'cancelled'
      return { status: 'cancelled' }
    },

    async simulateRequest({ kind, payee_name, amount }) {
      let finalAmount = amount
      if (kind === 'bill' && finalAmount === null) {
        const billAmount = BILLS[payee_name.toLowerCase()]
        if (billAmount === undefined) throw new ApiError(`I couldn't find a bill from ${payee_name}.`)
        finalAmount = billAmount
      }
      if (finalAmount === null) throw new ApiError('I need an amount for that payment.')

      for (const t of transfers.values()) {
        if (t.status === 'awaiting_yes') t.status = 'cancelled'
      }

      const said = lines.join(' ').toLowerCase()
      const payeeKey = payee_name.toLowerCase()
      const reasons: string[] = []
      let decision: CurrentTransfer['decision'] = 'allow'
      if (said.includes('safe account') || finalAmount > HOLD_OVER || heldPayees.has(payeeKey)) {
        decision = 'hold'
        if (said.includes('safe account')) reasons.push('You mentioned a "safe account"')
        if (finalAmount > HOLD_OVER) reasons.push('This is a very large amount')
        if (heldPayees.has(payeeKey)) reasons.push('A payment to this person was already stopped')
        heldPayees.add(payeeKey)
      } else if (finalAmount > CONFIRM_OVER) {
        decision = 'confirm'
        reasons.push('This is bigger than your usual payment')
      }

      counter += 1
      const t: CurrentTransfer = {
        transfer_id: `t_${counter}`,
        kind,
        status: decision === 'hold' ? 'held' : 'awaiting_yes',
        decision,
        risk_score: decision === 'hold' ? 85 : decision === 'confirm' ? 45 : 10,
        reasons,
        spoken_message:
          decision === 'hold'
            ? HOLD_MESSAGE
            : `I'll pay ${payee_name} ${formatMoney(finalAmount)} from your checking account. Are you sure?`,
        payee_name,
        amount: finalAmount,
        from_account_name: ACCOUNT_NAME,
      }
      transfers.set(t.transfer_id, t)
      current = t
      return { ...t }
    },

    executedCount() {
      return executed
    },
  }
}
