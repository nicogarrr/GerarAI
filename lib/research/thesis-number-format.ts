/** Only structured amounts are formatted here. Never rewrite a quoted source. */
export function thesisMoney(value: number, currency: string): string {
  return new Intl.NumberFormat('es-ES', {
    style: 'currency', currency, useGrouping: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}

/** The catalyst payload has no currency or share basis, so no symbol is inferred. */
export function thesisEps(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? 'N/D' : new Intl.NumberFormat('es-ES', {
    useGrouping: 'always',
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}
