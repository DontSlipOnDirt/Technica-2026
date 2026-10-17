import { useConversation } from '@elevenlabs/react'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createFakeApi } from '../api/fakeApi'
import { useVoiceSession } from './useVoiceSession'

vi.hoisted(() => vi.stubEnv('VITE_ELEVENLABS_AGENT_ID', 'agent_test'))
vi.mock('@elevenlabs/react', () => ({ useConversation: vi.fn() }))

describe('useVoiceSession ElevenLabs integration', () => {
  let callbacks: NonNullable<Parameters<typeof useConversation>[0]>
  const conversation = {
    status: 'disconnected',
    mode: 'listening',
    isMuted: false,
    setMuted: vi.fn(),
    startSession: vi.fn(),
    sendContextualUpdate: vi.fn(),
    getInputVolume: vi.fn(() => 0.4),
    getOutputVolume: vi.fn(() => 0.7),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    conversation.status = 'disconnected'
    conversation.mode = 'listening'
    conversation.isMuted = false
    vi.mocked(useConversation).mockImplementation((options) => {
      callbacks = options!
      return conversation as unknown as ReturnType<typeof useConversation>
    })
  })

  it('starts the configured agent and lets the SDK own microphone capture', () => {
    const { result } = renderHook(() => useVoiceSession(createFakeApi()))
    act(() => result.current.onMicTap())
    expect(conversation.startSession).toHaveBeenCalledWith({ agentId: 'agent_test', connectionType: 'websocket' })
  })

  it('shows connection errors reported by the SDK', () => {
    const { result } = renderHook(() => useVoiceSession(createFakeApi()))
    act(() => callbacks.onError?.('Connection failed'))
    expect(result.current.state.active).toBe(false)
    expect(result.current.state.messages.at(-1)?.text).toMatch(/couldn't connect/i)
  })

  it('provides microphone levels only while connected and unmuted', () => {
    conversation.status = 'connected'
    const api = createFakeApi()
    const { result, rerender } = renderHook(() => useVoiceSession(api))
    expect(result.current.getAudioLevel?.()).toBe(0.4)
    conversation.isMuted = true
    rerender()
    expect(result.current.getAudioLevel).toBeUndefined()
    conversation.isMuted = false
    conversation.status = 'disconnected'
    rerender()
    expect(result.current.getAudioLevel).toBeUndefined()
  })

  it('keeps the microphone paused after the reply until the user taps again', () => {
    conversation.status = 'connected'
    const api = createFakeApi()
    const { result, rerender } = renderHook(() => useVoiceSession(api))
    act(() => result.current.onMicTap())
    expect(conversation.setMuted).toHaveBeenCalledWith(true)
    conversation.isMuted = true
    rerender()
    expect(result.current.phase).toBe('paused')
    conversation.setMuted.mockClear()
    conversation.mode = 'speaking'
    rerender()
    expect(result.current.phase).toBe('speaking')
    expect(result.current.getAudioLevel?.()).toBe(0.7)
    expect(conversation.setMuted).not.toHaveBeenCalled()
    conversation.mode = 'listening'
    rerender()
    expect(conversation.setMuted).not.toHaveBeenCalled()
    expect(result.current.phase).toBe('paused')
    act(() => result.current.onMicTap())
    expect(conversation.setMuted).toHaveBeenCalledWith(false)
  })

  it('opens the mic when tapping during an agent reply', () => {
    conversation.status = 'connected'
    conversation.mode = 'speaking'
    conversation.isMuted = true
    const { result } = renderHook(() => useVoiceSession(createFakeApi()))
    act(() => result.current.onMicTap())
    expect(conversation.setMuted).toHaveBeenCalledWith(false)
  })

  it.each(['stop', 'STOP.', 'I am done talking.', "I'm done talking", 'I’m done talking'])('pauses microphone capture for the spoken command %s', (message) => {
    conversation.status = 'connected'
    const { result } = renderHook(() => useVoiceSession(createFakeApi()))
    act(() => callbacks.onMessage?.({ message, role: 'user', source: 'user', event_id: 1 }))
    expect(conversation.setMuted).toHaveBeenCalledWith(true)
    expect(result.current.state.messages.at(-1)?.text).toBe(message)
  })

  it.each([
    { message: 'Stop my payment', role: 'user' as const, source: 'user' as const },
    { message: 'stop', role: 'agent' as const, source: 'ai' as const },
  ])('does not pause for a banking request or agent speech: %j', (message) => {
    conversation.status = 'connected'
    renderHook(() => useVoiceSession(createFakeApi()))
    act(() => callbacks.onMessage?.({ ...message, event_id: 1 }))
    expect(conversation.setMuted).not.toHaveBeenCalled()
  })
})
