/**
 * Divisa del precio objetivo de analistas frente a la de la fila.
 *
 * Yahoo a veces solo tiene consenso para el listado de EE. UU. (ADR, en USD)
 * aunque la posición cotice en EUR (p. ej. ASML comprada en euros). Nunca se
 * pinta un objetivo en USD junto a un precio en EUR sin decirlo: si la app ya
 * tiene los tipos de cambio de la cartera (divisa base por unidad de divisa),
 * se convierte a la divisa de la fila; si no, se etiqueta «(ADR, USD)».
 */
export type TargetFxRate = { currency: string; rate: number; scope?: string; as_of?: string };

/** Tipo «divisa base por 1 unidad de `currency`»; la base vale 1. Prefiere el de posiciones. */
function baseRate(currency: string, rates: readonly TargetFxRate[], baseCurrency: string | null | undefined): number | null {
  const code = currency.toUpperCase();
  if (baseCurrency && code === baseCurrency.toUpperCase()) return 1;
  const usable = rates.filter((r) => r.currency?.toUpperCase() === code && Number.isFinite(r.rate) && r.rate > 0);
  const pick = usable.find((r) => r.scope === 'positions') ?? usable[0];
  return pick ? pick.rate : null;
}

/** Importe de `from` a `to` con los tipos de la cartera; null si falta alguno. */
export function convertWithPortfolioFx(
  value: number,
  from: string,
  to: string,
  rates: readonly TargetFxRate[] | null | undefined,
  baseCurrency: string | null | undefined,
): number | null {
  if (!Number.isFinite(value)) return null;
  if (from.toUpperCase() === to.toUpperCase()) return value;
  if (!rates || !baseCurrency) return null;
  const fromRate = baseRate(from, rates, baseCurrency);
  const toRate = baseRate(to, rates, baseCurrency);
  if (fromRate === null || toRate === null) return null;
  return (value * fromRate) / toRate;
}

/** Etiqueta del objetivo que se queda en su divisa por falta de tipo de cambio. */
export function unconvertedTargetLabel(targetCurrency: string): string {
  const code = targetCurrency.toUpperCase();
  return code === 'USD' ? '(ADR, USD)' : `(en ${code})`;
}
