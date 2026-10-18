import { useState, type ReactNode } from 'react'

/** Closing a notice only hides it; the transaction keeps its backend status. */
export function Notification({ children }: { children: ReactNode }) {
  const [dismissed, setDismissed] = useState(false)
  if (dismissed) return null
  return (
    <div className="notification">
      {children}
      <button type="button" className="notification__close" aria-label="Dismiss notification" onClick={() => setDismissed(true)}>
        <span aria-hidden="true">×</span>
      </button>
    </div>
  )
}
