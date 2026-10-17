// Connects the screen to ElevenLabs and the backend. The agent's tools run on the MCP server,
// so this hook only forwards what she says, checks for the current transfer, and handles taps.

import { useConversation } from '@elevenlabs/react'
import { useCallback, useEffect, useReducer, useRef } from 'react'
import type { BankApi } from '../api/types'
import type { VoiceScreenProps } from '../components/VoiceScreen'
import { initialScreenState, screenReducer } from './screenState'
import { answerNo, answerYes, checkCurrentTransfer, forwardUserLine } from './sessionSync'

const CHECK_EVERY_MS = 1000
const AGENT_ID = import.meta.env.VITE_ELEVENLABS_AGENT_ID as string | undefined

export function useVoiceSession(api: BankApi): VoiceScreenProps {
  const [state, dispatch] = useReducer(screenReducer, initialScreenState)
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const conversation = useConversation({
    onConnect: ({ conversationId }) => {
      const next = screenReducer(stateRef.current, { type: 'session_started', conversation_id: conversationId })
      stateRef.current = next
      dispatch({ type: 'session_started', conversation_id: conversationId })
    },
    onDisconnect: () => dispatch({ type: 'session_ended' }),
    onMessage: ({ role, message }) => {
      dispatch({ type: 'message', message: { role, text: message } })
      if (role === 'user') void forwardUserLine(api, stateRef.current, message)
    },
  })

  // When the agent starts answering, open the mic again so she can reply after it.
  const { mode, isMuted, setMuted } = conversation
  useEffect(() => {
    if (mode === 'speaking' && isMuted) setMuted(false)
  }, [mode, isMuted, setMuted])

  // While a session is live, check for the current transfer once a second.
  useEffect(() => {
    if (!state.active) return
    // Skip a check while the last one is still out, so a slow answer can't land after a newer one.
    let inFlight = false
    const check = async () => {
      if (inFlight) return
      inFlight = true
      try {
        await checkCurrentTransfer(api, dispatch)
      } finally {
        inFlight = false
      }
    }
    void check()
    const timer = setInterval(() => void check(), CHECK_EVERY_MS)
    return () => clearInterval(timer)
  }, [api, state.active])

  const connected = conversation.status === 'connected'

  const onMicTap = useCallback(async () => {
    if (connected) {
      // Tapping while she talks ends her turn: muting reads as silence to ElevenLabs.
      setMuted(!isMuted)
      return
    }
    if (!AGENT_ID) {
      // No agent configured (fake mode demo): run a local session so checking and taps still work.
      dispatch({ type: 'session_started', conversation_id: 'demo' })
      return
    }
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true })
      conversation.startSession({ agentId: AGENT_ID })
    } catch {
      dispatch({ type: 'message', message: { role: 'agent', text: 'I need microphone access to hear you.' } })
    }
  }, [connected, isMuted, setMuted, conversation])

  const tell = useCallback((text: string) => {
    if (connected) conversation.sendContextualUpdate(text)
  }, [connected, conversation])

  const onYes = useCallback(async () => {
    tell(await answerYes(api, stateRef.current, dispatch))
  }, [api, tell])

  const onNo = useCallback(async () => {
    tell(await answerNo(api, stateRef.current, dispatch))
  }, [api, tell])

  return { state, onMicTap: () => void onMicTap(), onYes, onNo }
}
