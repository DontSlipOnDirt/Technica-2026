import { describe, expect, it, vi } from 'vitest'
import { createFakeApi } from '../api/fakeApi'
import { ApiError } from '../api/types'
import { initialScreenState, screenReducer, type ScreenAction, type ScreenState } from './screenState'
import { answerNo, answerYes, checkCurrentTransfer, forwardUserLine } from './sessionSync'

function store(start: ScreenState = initialScreenState) {
  const box = { state: start }
  const dispatch = (a: ScreenAction) => {
    box.state = screenReducer(box.state, a)
  }
  return { box, dispatch }
}

const started = screenReducer(initialScreenState, { type: 'session_started', conversation_id: 'c1' })

describe('forwardUserLine', () => {
  it('forwards a user line under the conversation id', async () => {
    const api = createFakeApi()
    const spy = vi.spyOn(api, 'postTranscript')
    await forwardUserLine(api, started, 'hello')
    expect(spy).toHaveBeenCalledWith('c1', 'hello')
  })

  it('does not forward before a session starts or for blank text', async () => {
    const api = createFakeApi()
    const spy = vi.spyOn(api, 'postTranscript')
    await forwardUserLine(api, initialScreenState, 'hello')
    await forwardUserLine(api, started, '   ')
    expect(spy).not.toHaveBeenCalled()
  })

  it('a failed forward does not throw', async () => {
    const api = createFakeApi()
    vi.spyOn(api, 'postTranscript').mockRejectedValue(new TypeError('fetch failed'))
    await expect(forwardUserLine(api, started, 'hello')).resolves.toBeUndefined()
  })
})

describe('checkCurrentTransfer', () => {
  it('shows the latest transfer', async () => {
    const api = createFakeApi()
    const { box, dispatch } = store(started)
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 85 })
    await checkCurrentTransfer(api, dispatch)
    expect(box.state.panel).toBe('confirming')
  })

  it('a failed check leaves the screen as it was', async () => {
    const api = createFakeApi()
    const { box, dispatch } = store(started)
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 85 })
    await checkCurrentTransfer(api, dispatch)
    vi.spyOn(api, 'getCurrentTransfer').mockRejectedValue(new TypeError('fetch failed'))
    await checkCurrentTransfer(api, dispatch)
    expect(box.state.panel).toBe('confirming')
  })
})

describe('answerYes / answerNo', () => {
  async function pending(amount: number) {
    const api = createFakeApi()
    const { box, dispatch } = store(started)
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount })
    await checkCurrentTransfer(api, dispatch)
    return { api, box, dispatch }
  }

  it('Yes pays and shows sent', async () => {
    const { api, box, dispatch } = await pending(85)
    const result = await answerYes(api, box.state, dispatch)
    expect(result.startsWith('The customer tapped Yes. ')).toBe(true)
    expect(box.state.panel).toBe('sent')
  })

  it('Yes on a held transfer is refused without calling the bank', async () => {
    const { api, box, dispatch } = await pending(2000)
    const spy = vi.spyOn(api, 'confirmTransfer')
    const result = await answerYes(api, box.state, dispatch)
    expect(spy).not.toHaveBeenCalled()
    expect(result.endsWith('No money was moved.')).toBe(true)
    expect(box.state.panel).toBe('blocked')
  })

  it('Yes when the bank is unreachable says no money moved', async () => {
    const { api, box, dispatch } = await pending(85)
    vi.spyOn(api, 'confirmTransfer').mockRejectedValue(new TypeError('fetch failed'))
    const result = await answerYes(api, box.state, dispatch)
    expect(result).toBe("I couldn't reach the bank. No money was moved.")
    expect(box.state.panel).toBe('confirming')
  })

  it('Yes passes on the bank error message', async () => {
    const { api, box, dispatch } = await pending(85)
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 90 })
    // The screen still shows the first transfer, which the bank has now cancelled.
    const result = await answerYes(api, box.state, dispatch)
    expect(result).toBe("That payment can't be sent. No money was moved.")
  })

  it('No cancels', async () => {
    const { api, box, dispatch } = await pending(85)
    const result = await answerNo(api, box.state, dispatch)
    expect(box.state.panel).toBe('none')
    expect(result.endsWith('No money was moved.')).toBe(true)
  })
})

describe('review fixes', () => {
  async function pending85() {
    const api = createFakeApi()
    const { box, dispatch } = store(started)
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 85 })
    await checkCurrentTransfer(api, dispatch)
    return { api, box, dispatch }
  }

  it('No after a voice yes says it was sent, not that no money moved', async () => {
    const { api, box, dispatch } = await pending85()
    await api.confirmTransfer(box.state.transfer!.transfer_id) // the agent's voice yes
    const result = await answerNo(api, box.state, dispatch)
    expect(result).not.toContain('No money was moved')
    expect(result).toContain('already sent')
    expect(box.state.panel).toBe('sent')
  })

  it('a lost confirm response that actually went through is reported as sent', async () => {
    const { api, box, dispatch } = await pending85()
    const real = api.confirmTransfer.bind(api)
    vi.spyOn(api, 'confirmTransfer').mockImplementation(async (id) => {
      await real(id)
      throw new TypeError('fetch failed')
    })
    const result = await answerYes(api, box.state, dispatch)
    expect(result).not.toContain('No money was moved')
    expect(box.state.panel).toBe('sent')
  })

  it('a failed tap shows a message in the chat', async () => {
    const { api, box, dispatch } = await pending85()
    vi.spyOn(api, 'confirmTransfer').mockRejectedValue(new TypeError('fetch failed'))
    await answerYes(api, box.state, dispatch)
    expect(box.state.messages.at(-1)).toEqual({ role: 'agent', text: "I couldn't reach the bank. No money was moved." })
  })

  it('a failed tap never claims nothing moved when the bank cannot be asked again', async () => {
    const { api, box, dispatch } = await pending85()
    vi.spyOn(api, 'confirmTransfer').mockRejectedValue(new TypeError('fetch failed'))
    vi.spyOn(api, 'getCurrentTransfer').mockRejectedValue(new TypeError('fetch failed'))
    const result = await answerYes(api, box.state, dispatch)
    expect(result).not.toContain('No money was moved')
    expect(result).toContain('not sure that payment went through')
  })

  it('a payment the bank is unsure about is reported as unsure, not as failed', async () => {
    const { api, box, dispatch } = await pending85()
    const t = box.state.transfer!
    vi.spyOn(api, 'confirmTransfer').mockRejectedValue(new ApiError("I'm not sure that payment went through."))
    vi.spyOn(api, 'getCurrentTransfer').mockResolvedValue({ ...t, status: 'unknown' })
    const result = await answerYes(api, box.state, dispatch)
    expect(result).not.toContain('No money was moved')
    expect(box.state.panel).toBe('unsure')
    // A second tap on the same request doesn't claim nothing moved either.
    expect(await answerNo(api, box.state, dispatch)).not.toContain('No money was moved')
  })

  it('a refused tap shows a message in the chat', async () => {
    const api = createFakeApi()
    const { box, dispatch } = store(started)
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Bob', amount: 2000 })
    await checkCurrentTransfer(api, dispatch)
    await answerYes(api, box.state, dispatch)
    expect(box.state.messages.at(-1)?.text.endsWith('No money was moved.')).toBe(true)
  })
})
