import { useState } from 'react'
import type { CurrentTransfer } from '../api/types'
import { formatMoney } from '../money'

interface ConfirmPanelProps {
  transfer: CurrentTransfer
  onYes(): Promise<void>
  onNo(): Promise<void>
}

/** "Are you sure?" with big Yes/No buttons. Both lock after one tap so a payment can't be sent twice. */
export function ConfirmPanel({ transfer, onYes, onNo }: ConfirmPanelProps) {
  const [busy, setBusy] = useState(false)

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
        Pay {transfer.payee_name} {formatMoney(transfer.amount)} from {transfer.from_account_name}?
      </p>
      {transfer.decision === 'confirm' && transfer.reasons.length > 0 && (
        <ul className="confirm__warning">
          {transfer.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <div className="confirm__buttons">
        <button type="button" className="btn btn--yes" disabled={busy} onClick={() => answer(onYes)}>
          ✓ Yes, pay it
        </button>
        <button type="button" className="btn btn--no" disabled={busy} onClick={() => answer(onNo)}>
          ✕ No, cancel
        </button>
      </div>
    </section>
  )
}
