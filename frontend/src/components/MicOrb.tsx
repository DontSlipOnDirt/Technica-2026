import { useEffect, useRef } from 'react'

export type VoicePhase = 'idle' | 'connecting' | 'listening' | 'waiting' | 'speaking' | 'paused'

interface MicOrbProps {
  active: boolean
  blocked: boolean
  onTap(): void
  phase?: VoicePhase
  micMuted?: boolean
  getAudioLevel?(): number
}

export function MicOrb({ active, blocked, phase, micMuted, getAudioLevel, onTap }: MicOrbProps) {
  const buttonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const button = buttonRef.current
    if (!button) return
    button.style.setProperty('--mic-level', '0')
    if (!active || blocked || !getAudioLevel) return
    let frame: number
    const update = () => {
      const sample = getAudioLevel()
      const level = Number.isFinite(sample) ? Math.min(1, Math.max(0, (sample - 0.05) * 3)) : 0
      button.style.setProperty('--mic-level', String(level))
      frame = requestAnimationFrame(update)
    }
    frame = requestAnimationFrame(update)
    return () => {
      cancelAnimationFrame(frame)
      button.style.setProperty('--mic-level', '0')
    }
  }, [active, blocked, getAudioLevel])

  const className = ['orb', active && 'orb--active', phase && `orb--${phase}`, blocked && 'orb--blocked'].filter(Boolean).join(' ')
  const label = phase === 'connecting' ? 'Connecting'
    : micMuted ? 'Start listening'
    : phase === 'waiting' ? 'Talk again'
    : phase === 'speaking' ? 'Done talking'
    : active ? 'Done talking' : 'Talk'
  return (
    <button ref={buttonRef} type="button" className={className} aria-label={label} disabled={phase === 'connecting'} onClick={onTap}>
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
