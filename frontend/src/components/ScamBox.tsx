import type { CurrentTransfer, Kind } from '../api/types'
import { formatMoney } from '../money'

// Capital One's general customer service line, from capitalone.com/help-center/contact-us.
export const CAPITAL_ONE_PHONE = '1-877-383-4802'

const OPERATION: Record<Exclude<Kind, 'new_account'>, string> = {
  transfer: 'transfer',
  own_transfer: 'transfer',
  bill: 'bill payment',
  loan: 'loan payment',
  withdrawal: 'withdrawal',
  deposit: 'deposit',
}

/** Shown when the fraud check holds a transfer. Calling Capital One is the only way forward. */
export function ScamBox({ transfer }: { transfer: CurrentTransfer }) {
  const stopped = transfer.kind === 'new_account'
    ? 'We did not open the new account.'
    : `We stopped your ${formatMoney(transfer.amount)} ${OPERATION[transfer.kind]}.`
  return (
    <section className="scam" role="alert">
      <h2 className="scam__title">This looks like a scam</h2>
      <p>{stopped} Your money has not moved.</p>
      {transfer.reasons.length > 0 && (
        <ul className="scam__reasons">
          {transfer.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <a className="scam__call" href={`tel:${CAPITAL_ONE_PHONE.replace(/-/g, '')}`}>
        Call Capital One
        <span className="scam__phone">{CAPITAL_ONE_PHONE}</span>
      </a>
    </section>
  )
}
