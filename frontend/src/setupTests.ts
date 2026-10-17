import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest doesn't enable Testing Library's automatic cleanup, so unmount after each test.
afterEach(cleanup)
