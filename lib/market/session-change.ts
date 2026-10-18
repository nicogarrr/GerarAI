/** A provider's placeholder zero is not a session return without a prior close. */
export function hasPriorClose(quote: { pc?: number | null } | null | undefined): boolean {
  return typeof quote?.pc === 'number' && Number.isFinite(quote.pc) && quote.pc > 0;
}
