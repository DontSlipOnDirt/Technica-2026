import type { ScreenState } from '../session/screenState'
import { Chat } from './Chat'
import { ConfirmPanel } from './ConfirmPanel'
import { MicOrb } from './MicOrb'
import { ScamBox } from './ScamBox'
import { SentBox } from './SentBox'

export interface VoiceScreenProps {
  state: ScreenState
  onMicTap(): void
  onYes(): Promise<void>
  onNo(): Promise<void>
}

function statusLine(state: ScreenState): string {
  if (state.panel === 'blocked') return 'Transfer stopped'
  if (state.panel === 'confirming') return 'Say yes or no'
  return state.active ? 'Listening…' : 'Tap to talk'
}

/** The one voice screen: logo, mic, status, the current panel, and the chat. */
export function VoiceScreen({ state, onMicTap, onYes, onNo }: VoiceScreenProps) {
  const { panel, transfer } = state
  return (
    <main className={`screen${panel === 'blocked' ? ' screen--blocked' : ''}`}>
      <header className="screen__header">
        <img src="/capitalone-logo.svg" alt="Capital One" className="screen__logo" />
        <span className="screen__label">Voice</span>
      </header>

      <div className="screen__mic">
        <MicOrb active={state.active} blocked={panel === 'blocked'} onTap={onMicTap} />
        <p className="screen__status">{statusLine(state)}</p>
      </div>

      {panel === 'confirming' && transfer && (
        <ConfirmPanel key={transfer.transfer_id} transfer={transfer} onYes={onYes} onNo={onNo} />
      )}
      {panel === 'sent' && state.sentText && <SentBox text={state.sentText} />}
      {panel === 'blocked' && transfer && <ScamBox transfer={transfer} />}

      <Chat messages={state.messages} />
    </main>
  )
}
