import { describe, expect, it } from 'vitest'
import type { CurrentTransfer } from '../api/types'
import { initialScreenState, screenReducer, type ScreenState } from './screenState'

function transfer(over: Partial<CurrentTransfer> = {}): CurrentTransfer {
  return {
    transfer_id: 't_1',
    kind: 'bill',
    status: 'awaiting_yes',
    decision: 'allow',
    risk_score: 10,
    reasons: [],
    spoken_message: '',
    payee_name: 'Pepco',
    amount: 600,
    from_account_name: 'Checking',
    ...over,
  }
}

function withTransfer(t: CurrentTransfer, state: ScreenState = initialScreenState): ScreenState {
  return screenReducer(state, { type: 'current', transfer: t })
}

describe('screenReducer', () => {
  it.each([
    { kind: 'withdrawal' as const, message: '$1.00 has been withdrawn from Checking.' },
    { kind: 'deposit' as const, message: '$1.00 has been deposited into Checking.' },
  ])('describes an executed $kind accurately', ({ kind, message }) => {
    const state = withTransfer(transfer({ kind, amount: 1, status: 'executed' }))
    expect(state.panel).toBe('sent')
    expect(state.sentText).toBe(message)
  })

  it('held shows the scam panel', () => {
    const s = withTransfer(transfer({ status: 'held', decision: 'hold' }))
    expect(s.panel).toBe('blocked')
  })

  it('awaiting_yes shows the Are-you-sure panel', () => {
    const s = withTransfer(transfer())
    expect(s.panel).toBe('confirming')
    expect(s.transfer?.transfer_id).toBe('t_1')
  })

  it('a new transfer replaces the scam panel', () => {
    const held = withTransfer(transfer({ status: 'held', decision: 'hold' }))
    const s = withTransfer(transfer({ transfer_id: 't_2' }), held)
    expect(s.panel).toBe('confirming')
  })

  it('a new transfer replaces the pending one', () => {
    const first = withTransfer(transfer())
    const s = withTransfer(transfer({ transfer_id: 't_2' }), first)
    expect(s.transfer?.transfer_id).toBe('t_2')
  })

  it('executed shows sent copy for bills and transfers', () => {
    const bill = withTransfer(transfer({ status: 'executed' }))
    expect(bill.panel).toBe('sent')
    expect(bill.sentText).toBe('Your Pepco bill of $600.00 has been sent.')

    const sent = withTransfer(transfer({ status: 'executed', kind: 'transfer', payee_name: 'Maria', amount: 50 }))
    expect(sent.sentText).toBe('$50.00 has been sent to Maria.')
  })

  it('cancelled clears the panel', () => {
    const s = withTransfer(transfer({ status: 'cancelled' }), withTransfer(transfer()))
    expect(s.panel).toBe('none')
  })

  it('null leaves the screen as it was', () => {
    const before = withTransfer(transfer({ status: 'held', decision: 'hold' }))
    const after = screenReducer(before, { type: 'current', transfer: null })
    expect(after.panel).toBe('blocked')
  })

  it('same transfer and status returns the same state object', () => {
    const before = withTransfer(transfer())
    expect(withTransfer(transfer(), before)).toBe(before)
  })

  it('session_ended keeps the scam panel', () => {
    const started = screenReducer(initialScreenState, { type: 'session_started', conversation_id: 'c1' })
    const held = withTransfer(transfer({ status: 'held', decision: 'hold' }), started)
    const ended = screenReducer(held, { type: 'session_ended' })
    expect(ended.active).toBe(false)
    expect(ended.panel).toBe('blocked')
  })

  it('session_started records the conversation', () => {
    const s = screenReducer(initialScreenState, { type: 'session_started', conversation_id: 'c1' })
    expect(s.active).toBe(true)
    expect(s.conversation_id).toBe('c1')
  })

  it('messages append in order', () => {
    let s = screenReducer(initialScreenState, { type: 'message', message: { role: 'user', text: 'hi' } })
    s = screenReducer(s, { type: 'message', message: { role: 'agent', text: 'hello' } })
    expect(s.messages.map((m) => m.text)).toEqual(['hi', 'hello'])
  })
})

describe('stale checks', () => {
  it('a finished transfer never goes back to waiting for a yes', () => {
    const sent = withTransfer(transfer({ status: 'executed' }), withTransfer(transfer()))
    const stale = withTransfer(transfer({ status: 'awaiting_yes' }), sent)
    expect(stale.panel).toBe('sent')
  })

  it('a held transfer never goes back to waiting for a yes', () => {
    const held = withTransfer(transfer({ status: 'held', decision: 'hold' }))
    expect(withTransfer(transfer({ status: 'awaiting_yes' }), held).panel).toBe('blocked')
  })
})
