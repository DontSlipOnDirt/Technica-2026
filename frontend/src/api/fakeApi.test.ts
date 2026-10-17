import { describe, expect, it } from 'vitest'
import { createFakeApi } from './fakeApi'
import { ApiError } from './types'

describe('fake bank API', () => {
  it('uses every user line from the conversation', async () => {
    const api = createFakeApi()
    await api.postTranscript('c1', 'the bank said move it to a safe account')
    await api.postTranscript('c1', 'four hundred dollars')
    const t = await api.simulateRequest({ kind: 'transfer', payee_name: 'Bob', amount: 400 })
    expect(t.status).toBe('held')
  })

  it('a new conversation starts with a clean transcript', async () => {
    const api = createFakeApi()
    await api.postTranscript('c1', 'move it to a safe account')
    await api.postTranscript('c2', 'pay my electric bill')
    const t = await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 85 })
    expect(t.status).toBe('awaiting_yes')
  })

  it('keeps holding a payee after a hold, whatever the wording', async () => {
    const api = createFakeApi()
    await api.postTranscript('c1', 'move it to a safe account')
    await api.simulateRequest({ kind: 'transfer', payee_name: 'Bob', amount: 400 })
    await api.postTranscript('c2', 'just send fifty dollars')
    const again = await api.simulateRequest({ kind: 'transfer', payee_name: 'Bob', amount: 50 })
    expect(again.status).toBe('held')
  })

  it('allows under 300, confirms 300 to 1000, holds over 1000', async () => {
    const api = createFakeApi()
    expect((await api.simulateRequest({ kind: 'transfer', payee_name: 'A', amount: 85 })).decision).toBe('allow')
    const mid = await api.simulateRequest({ kind: 'transfer', payee_name: 'B', amount: 600 })
    expect(mid.decision).toBe('confirm')
    expect(mid.reasons).toHaveLength(1)
    expect((await api.simulateRequest({ kind: 'transfer', payee_name: 'C', amount: 1500 })).decision).toBe('hold')
  })

  it('fills a bill amount from Pepco', async () => {
    const api = createFakeApi()
    const t = await api.simulateRequest({ kind: 'bill', payee_name: 'Pepco', amount: null })
    expect(t.amount).toBe(600)
  })

  it('rejects an unknown biller', async () => {
    const api = createFakeApi()
    await expect(api.simulateRequest({ kind: 'bill', payee_name: 'Nobody', amount: null })).rejects.toBeInstanceOf(ApiError)
  })

  it('current transfer is the latest one', async () => {
    const api = createFakeApi()
    expect(await api.getCurrentTransfer()).toBeNull()
    const t = await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 50 })
    expect((await api.getCurrentTransfer())?.transfer_id).toBe(t.transfer_id)
  })

  it('a new request cancels the older pending one', async () => {
    const api = createFakeApi()
    const a = await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 50 })
    const b = await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 60 })
    await expect(api.confirmTransfer(a.transfer_id)).rejects.toBeInstanceOf(ApiError)
    await expect(api.confirmTransfer(b.transfer_id)).resolves.toEqual({ status: 'executed' })
  })

  it('refuses to confirm a held transfer', async () => {
    const api = createFakeApi()
    const t = await api.simulateRequest({ kind: 'transfer', payee_name: 'Bob', amount: 2000 })
    await expect(api.confirmTransfer(t.transfer_id)).rejects.toBeInstanceOf(ApiError)
  })

  it('confirming twice pays once', async () => {
    const api = createFakeApi()
    const t = await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 50 })
    await expect(api.confirmTransfer(t.transfer_id)).resolves.toEqual({ status: 'executed' })
    await expect(api.confirmTransfer(t.transfer_id)).resolves.toEqual({ status: 'executed' })
    expect(api.executedCount()).toBe(1)
    expect((await api.getCurrentTransfer())?.status).toBe('executed')
  })

  it('cancel marks the pending transfer cancelled', async () => {
    const api = createFakeApi()
    const t = await api.simulateRequest({ kind: 'transfer', payee_name: 'Maria', amount: 50 })
    await expect(api.cancelTransfer(t.transfer_id)).resolves.toEqual({ status: 'cancelled' })
    expect((await api.getCurrentTransfer())?.status).toBe('cancelled')
  })
})
