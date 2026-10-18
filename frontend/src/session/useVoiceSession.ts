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

// "Stop", "wait", "hold on", "one moment", "pause", "I'm done talking"... but only when that's all she
// says, so "stop my payment" or "wait, pay Pepco" stay banking requests.
const MOMENT = '(?: a (?:minute|moment|second|sec))?'
const PAUSE_COMMAND = new RegExp(
  '^(?:(?:ok(?:ay)?|um+|uh+|oh)[,\\s]+)?'
  + `(?:stop(?: listening| talking)?|wait${MOMENT}|hold on${MOMENT}|hang on${MOMENT}|pause`
  + '|(?:just |give me )?(?:a|one) (?:minute|moment|second|sec)|(?:i am|i[\'’]m) done talking)'
  + '(?:,? please)?[.!?]*$',
  'i',
)

/** How long the agent stays silent after a pause before checking in. */
export const PAUSE_MS = 60_000
export const PAUSED_NOTE = 'The customer asked you to pause. Say nothing until they speak again.'
export const RESUME_MESSAGE = 'The customer paused a minute ago. Gently ask if they are ready to continue.'

export function isPauseCommand(text: string): boolean {
  return PAUSE_COMMAND.test(text.trim().replace(/\s+/g, ' '))
}

export function useVoiceSession(api: BankApi): VoiceScreenProps {
  const [state, dispatch] = useReducer(screenReducer, initialScreenState)
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  // A spoken pause mutes the mic; after PAUSE_MS the mic comes back on and the agent checks in.
  const pauseTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const endPause = useCallback(() => {
    if (pauseTimer.current) clearTimeout(pauseTimer.current)
    pauseTimer.current = null
  }, [])

  const conversation = useConversation({
    onConnect: ({ conversationId }) => {
      const next = screenReducer(stateRef.current, { type: 'session_started', conversation_id: conversationId })
      stateRef.current = next
      dispatch({ type: 'session_started', conversation_id: conversationId })
    },
    onDisconnect: () => {
      endPause()
      dispatch({ type: 'session_ended' })
    },
    onError: () => {
      dispatch({ type: 'message', message: { role: 'agent', text: "I couldn't connect to the voice agent. Check microphone access and try again." } })
    },
    onMessage: ({ role, message }) => {
      if (role === 'user' && message === RESUME_MESSAGE) return   // Our own nudge, not her words.
      dispatch({ type: 'message', message: { role, text: message } })
      if (role === 'user') {
        if (conversation.status === 'connected' && isPauseCommand(message)) {
          conversation.setMuted(true)
          conversation.sendContextualUpdate(PAUSED_NOTE)
          endPause()
          pauseTimer.current = setTimeout(() => {
            pauseTimer.current = null
            const live = conversationRef.current
            if (live.status !== 'connected') return
            live.setMuted(false)
            live.sendUserMessage(RESUME_MESSAGE)
          }, PAUSE_MS)
        } else {
          endPause()   // She spoke again, so the pause is over.
          void forwardUserLine(api, stateRef.current, message)
        }
      }
    },
  })
  const conversationRef = useRef(conversation)
  useEffect(() => {
    conversationRef.current = conversation
  })
  useEffect(() => endPause, [endPause])

  const { mode, isMuted, setMuted } = conversation

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
      endPause()   // A tap takes over from the pause timer.
      setMuted(!isMuted)
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
  }, [connected, isMuted, setMuted, conversation, endPause])

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
    : isMuted ? 'paused' : 'listening'
  const getAudioLevel = !connected ? undefined
    : mode === 'speaking' ? conversation.getOutputVolume
    : !isMuted ? conversation.getInputVolume : undefined

  return { state, phase, micMuted: isMuted, getAudioLevel, onMicTap, onYes, onNo }
}
