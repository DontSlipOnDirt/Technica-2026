// Talks to the team's backend. Every non-2xx answer becomes an ApiError with the backend's message.

import { ApiError, type BankApi, type CurrentTransfer } from './types'

export function createRealApi(base: string): BankApi {
  async function call<T>(path: string, body?: unknown): Promise<T> {
    let res: Response
    try {
      res = await fetch(`${base}${path}`, body === undefined
        ? { method: 'GET' }
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    } catch {
      throw new ApiError("I couldn't reach the bank.")
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new ApiError(typeof data?.error === 'string' ? data.error : 'Something went wrong at the bank.')
    return data as T
  }

  return {
    async postTranscript(conversation_id, text) {
      await call('/api/transcript', { conversation_id, text })
    },
    async getCurrentTransfer() {
      const data = await call<{ transfer: CurrentTransfer | null }>('/api/transfer/current')
      return data.transfer ?? null
    },
    confirmTransfer(transfer_id) {
      return call('/api/transfer/confirm', { transfer_id })
    },
    cancelTransfer(transfer_id) {
      return call('/api/transfer/cancel', { transfer_id })
    },
  }
}
