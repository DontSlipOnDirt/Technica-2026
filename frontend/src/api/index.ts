// Picks the backend: the in-browser stand-in by default, the real one when VITE_USE_FAKE_API=false.

import { createFakeApi, type FakeBankApi } from './fakeApi'
import { createRealApi } from './realApi'
import type { BankApi } from './types'

declare global {
  interface Window {
    /** In fake mode, call fakeApi.simulateRequest(...) from the console to play the MCP server's part. */
    fakeApi?: FakeBankApi
  }
}

export const usingFakeApi = import.meta.env.VITE_USE_FAKE_API !== 'false'

function pickApi(): BankApi {
  if (!usingFakeApi) return createRealApi(import.meta.env.VITE_API_BASE ?? '')
  const fake = createFakeApi()
  window.fakeApi = fake
  return fake
}

export const api: BankApi = pickApi()
