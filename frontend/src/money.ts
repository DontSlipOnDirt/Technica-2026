const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** Money is always dollars as a decimal number, shown like $2,000.00. */
export function formatMoney(amount: number): string {
  return dollars.format(amount)
}
