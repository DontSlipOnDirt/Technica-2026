interface MicOrbProps {
  active: boolean
  blocked: boolean
  onTap(): void
}

/** The big round button. Rings pulse while the session is live; a red shield shows when a scam was stopped. */
export function MicOrb({ active, blocked, onTap }: MicOrbProps) {
  const className = ['orb', active && 'orb--active', blocked && 'orb--blocked'].filter(Boolean).join(' ')
  return (
    <button type="button" className={className} aria-label={active ? 'Done talking' : 'Talk'} onClick={onTap}>
      <span className="orb__ring" />
      <span className="orb__ring orb__ring--2" />
      <span className="orb__ring orb__ring--3" />
      <span className="orb__core">
        {blocked ? (
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" /></svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z" /></svg>
        )}
      </span>
    </button>
  )
}
