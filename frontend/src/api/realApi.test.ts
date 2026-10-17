import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRealApi } from './realApi'
import { ApiError } from './types'

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('real bank API', () => {
  it('posts transcript lines', async () => {
    const fetchMock = respond(200, { ok: true })
    vi.stubGlobal('fetch', fetchMock)
    await createRealApi('https://bank.test').postTranscript('c1', 'hello')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://bank.test/api/transcript')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ conversation_id: 'c1', text: 'hello' })
  })

  it('unwraps the current transfer', async () => {
    vi.stubGlobal('fetch', respond(200, { transfer: null }))
    await expect(createRealApi('').getCurrentTransfer()).resolves.toBeNull()
  })

  it('turns {"error": "..."} into ApiError with that message', async () => {
    vi.stubGlobal('fetch', respond(400, { error: "That payment can't be sent." }))
    const err = await createRealApi('').confirmTransfer('t_1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe("That payment can't be sent.")
  })

  it('sends the transfer id to confirm and cancel', async () => {
    const fetchMock = respond(200, { status: 'cancelled' })
    vi.stubGlobal('fetch', fetchMock)
    await createRealApi('').cancelTransfer('t_9')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/transfer/cancel')
    expect(JSON.parse(init.body as string)).toEqual({ transfer_id: 't_9' })
  })
})
