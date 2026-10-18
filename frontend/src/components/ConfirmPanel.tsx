import { useState } from 'react'
import type { CurrentTransfer } from '../api/types'
import { formatMoney } from '../money'

interface ConfirmPanelProps {
  transfer: CurrentTransfer
  onYes(): Promise<void>
  onNo(): Promise<void>
}

/** The question and the Yes button's words for each kind of request. */
function describe(t: CurrentTransfer): { question: string; yesLabel: string } {
  const money = formatMoney(t.amount)
  switch (t.kind) {
    case 'withdrawal':
      return { question: `Withdraw ${money} from ${t.from_account_name}?`, yesLabel: '✓ Yes, withdraw' }
    case 'deposit':
      return { question: `Deposit ${money} into ${t.from_account_name}?`, yesLabel: '✓ Yes, deposit' }
    case 'own_transfer':
      return { question: `Move ${money} from ${t.from_account_name} to ${t.payee_name}?`, yesLabel: '✓ Yes, move it' }
    case 'loan':
      return { question: `Pay ${money} toward ${t.payee_name} from ${t.from_account_name}?`, yesLabel: '✓ Yes, pay it' }
    case 'new_account': {
      const type = t.account_type ? `${t.account_type} ` : ''
      const called = t.payee_name !== t.account_type ? ` called ${t.payee_name}` : ''
      return { question: `Open a new ${type}account${called}?`, yesLabel: '✓ Yes, open it' }
    }
    case 'transfer':
    case 'bill':
      return { question: `Pay ${t.payee_name} ${money} from ${t.from_account_name}?`, yesLabel: '✓ Yes, pay it' }
  }
}

/** "Are you sure?" with big Yes/No buttons. Both lock after one tap so a payment can't be sent twice. */
export function ConfirmPanel({ transfer, onYes, onNo }: ConfirmPanelProps) {
  const [busy, setBusy] = useState(false)
  const { question, yesLabel } = describe(transfer)

  async function answer(handler: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    try {
      await handler()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="confirm">
      <p className="confirm__question">
        {question}
      </p>
      {transfer.decision === 'confirm' && transfer.reasons.length > 0 && (
        <ul className="confirm__warning">
          {transfer.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <div className="confirm__buttons">
        <button type="button" className="btn btn--yes" disabled={busy} onClick={() => answer(onYes)}>
          {yesLabel}
        </button>
        <button type="button" className="btn btn--no" disabled={busy} onClick={() => answer(onNo)}>
          ✕ No, cancel
        </button>
      </div>
    </section>
  )
}
