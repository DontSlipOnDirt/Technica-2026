import { ConversationProvider } from '@elevenlabs/react'
import { api } from './api'
import { VoiceScreen } from './components/VoiceScreen'
import { useVoiceSession } from './session/useVoiceSession'

function VoiceApp() {
  return <VoiceScreen {...useVoiceSession(api)} />
}

export function App() {
  return (
    <ConversationProvider>
      <VoiceApp />
    </ConversationProvider>
  )
}
