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
    onError: () => {
      dispatch({ type: 'message', message: { role: 'agent', text: "I couldn't connect to the voice agent. Check microphone access and try again." } })
    },
    onMessage: ({ role, message }) => {
      dispatch({ type: 'message', message: { role, text: message } })
      if (role === 'user') void forwardUserLine(api, stateRef.current, message)
    },
  })

  const { mode, isMuted, setMuted } = conversation
  const previousMode = useRef(mode)
  useEffect(() => {
    if (previousMode.current === 'speaking' && mode === 'listening' && isMuted) setMuted(false)
    previousMode.current = mode
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

  const onMicTap = useCallback(() => {
    if (connected) {
      setMuted(mode === 'speaking' ? false : !isMuted)
      return
    }
    if (conversation.status === 'connecting') return
    if (!AGENT_ID) {
      // No agent configured (fake mode demo): run a local session so checking and taps still work.
      dispatch({ type: 'session_started', conversation_id: 'demo' })
      return
    }
    try {
      conversation.startSession({ agentId: AGENT_ID, connectionType: 'websocket' })
    } catch {
      dispatch({ type: 'message', message: { role: 'agent', text: 'I need microphone access to hear you.' } })
    }
  }, [connected, mode, isMuted, setMuted, conversation])

  const tell = useCallback((text: string) => {
    if (connected) conversation.sendContextualUpdate(text)
  }, [connected, conversation])

  const onYes = useCallback(async () => {
    tell(await answerYes(api, stateRef.current, dispatch))
  }, [api, tell])

  const onNo = useCallback(async () => {
    tell(await answerNo(api, stateRef.current, dispatch))
  }, [api, tell])

  const phase = conversation.status === 'connecting' ? 'connecting'
    : !connected ? 'idle'
    : mode === 'speaking' ? 'speaking'
    : isMuted ? 'waiting' : 'listening'
  const getAudioLevel = !connected ? undefined
    : mode === 'speaking' ? conversation.getOutputVolume
    : !isMuted ? conversation.getInputVolume : undefined

  return { state, phase, getAudioLevel, onMicTap, onYes, onNo }
}
