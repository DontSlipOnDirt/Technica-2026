import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CurrentTransfer } from '../api/types'
import { initialScreenState, screenReducer, type ScreenState } from '../session/screenState'
import { VoiceScreen } from './VoiceScreen'

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

function stateWith(t: CurrentTransfer | null, active = true): ScreenState {
  let s = active ? screenReducer(initialScreenState, { type: 'session_started', conversation_id: 'c1' }) : initialScreenState
  if (t) s = screenReducer(s, { type: 'current', transfer: t })
  return s
}

function show(state: ScreenState, onYes = vi.fn(async () => {}), onNo = vi.fn(async () => {})) {
  render(<VoiceScreen state={state} onMicTap={vi.fn()} onYes={onYes} onNo={onNo} />)
  return { onYes, onNo }
}

describe('VoiceScreen', () => {
  it('idle shows Tap to talk and the logo', () => {
    show(stateWith(null, false))
    expect(screen.getByText('Tap to talk')).toBeInTheDocument()
    expect(screen.getByAltText('Capital One')).toBeInTheDocument()
  })

  it('confirming shows the payment and both buttons', () => {
    show(stateWith(transfer()))
    expect(screen.getByText('Pay Pepco $600.00 from Checking?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '✓ Yes, pay it' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '✕ No, cancel' })).toBeInTheDocument()
  })

  it('warning bar only for confirm', () => {
    const { unmount } = render(
      <VoiceScreen
        state={stateWith(transfer({ decision: 'confirm', reasons: ['This is bigger than your usual payment'] }))}
        onMicTap={vi.fn()} onYes={vi.fn(async () => {})} onNo={vi.fn(async () => {})}
      />,
    )
    expect(screen.getByText('This is bigger than your usual payment')).toBeInTheDocument()
    unmount()
    show(stateWith(transfer({ decision: 'allow', reasons: ['Should not show'] })))
    expect(screen.queryByText('Should not show')).toBeNull()
  })

  it('Yes is disabled while confirming', async () => {
    const onYes = vi.fn(() => new Promise<void>(() => {}))
    show(stateWith(transfer()), onYes)
    const yes = screen.getByRole('button', { name: '✓ Yes, pay it' })
    await userEvent.click(yes)
    await userEvent.click(yes)
    expect(onYes).toHaveBeenCalledTimes(1)
    expect(yes).toBeDisabled()
    expect(screen.getByRole('button', { name: '✕ No, cancel' })).toBeDisabled()
  })

  it('scam panel has no way through', () => {
    show(stateWith(transfer({
      kind: 'transfer', status: 'held', decision: 'hold', amount: 2000, payee_name: 'Bob',
      reasons: ['You mentioned a "safe account"'],
    })))
    expect(screen.getByRole('heading', { name: 'This looks like a scam' })).toBeInTheDocument()
    expect(screen.getByText('We stopped your $2,000.00 transfer. Your money has not moved.')).toBeInTheDocument()
    expect(screen.getByText('You mentioned a "safe account"')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Call Capital One/ }).getAttribute('href')).toMatch(/^tel:/)
    expect(screen.queryByRole('button', { name: /yes|release|send/i })).toBeNull()
    expect(screen.getByText('Transfer stopped')).toBeInTheDocument()
  })

  it('sent shows the sent text', () => {
    show(stateWith(transfer({ status: 'executed' })))
    expect(screen.getByText(/Your Pepco bill of \$600\.00 has been sent\./)).toBeInTheDocument()
  })

  it('chat shows both sides', () => {
    let s = stateWith(null)
    s = screenReducer(s, { type: 'message', message: { role: 'user', text: 'Pay my electric bill.' } })
    s = screenReducer(s, { type: 'message', message: { role: 'agent', text: 'Your Pepco bill is $600.00.' } })
    show(s)
    expect(screen.getByText('Pay my electric bill.')).toBeInTheDocument()
    expect(screen.getByText('Your Pepco bill is $600.00.')).toBeInTheDocument()
  })

  it('mic button says Talk when idle and Done talking when active', () => {
    const { unmount } = render(
      <VoiceScreen state={stateWith(null, false)} onMicTap={vi.fn()} onYes={vi.fn(async () => {})} onNo={vi.fn(async () => {})} />,
    )
    expect(screen.getByRole('button', { name: 'Talk' })).toBeInTheDocument()
    unmount()
    show(stateWith(null, true))
    expect(screen.getByRole('button', { name: 'Done talking' })).toBeInTheDocument()
  })
})
