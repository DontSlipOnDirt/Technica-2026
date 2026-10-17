import { describe, expect, it } from 'vitest'
import { formatMoney } from './money'

describe('formatMoney', () => {
  it('shows dollars with two decimals and thousands separators', () => {
    expect(formatMoney(600)).toBe('$600.00')
    expect(formatMoney(2000)).toBe('$2,000.00')
    expect(formatMoney(109.55)).toBe('$109.55')
  })
})
