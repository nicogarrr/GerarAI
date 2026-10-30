/**
 * Divisa del precio objetivo de analistas frente a la de la fila.
 *
 * Yahoo a veces solo tiene consenso para el listado de EE. UU. (ADR, en USD)
 * aunque la posición cotice en EUR (p. ej. ASML comprada en euros). Nunca se
 * pinta un objetivo en USD junto a un precio en EUR sin decirlo: si la app ya
 * tiene los tipos de cambio de la cartera (divisa base por unidad de divisa),
 * se convierte a la divisa de la fila; si no, se etiqueta «(ADR, USD)».
 */
import { chartPriceUnit } from '@/lib/market/chart-price-units';

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
    // Subunidades (peniques «GBp»/«GBX», centavos «ZAc»): se pasan a la unidad
    // mayor de forma exacta (÷100) antes de buscar tipo de cambio. Comparar
    // códigos en mayúsculas confundía «GBp» con «GBP» (×100) y un objetivo en
    // GBX frente a una fila en GBP quedaba sin convertir (sin recorrido).
    const fromUnit = chartPriceUnit(from);
    const toUnit = chartPriceUnit(to);
    if (!fromUnit || !toUnit) return null;
    const major = value / fromUnit.divisor;
    if (fromUnit.currency === toUnit.currency) return major * toUnit.divisor;
    if (!rates || !baseCurrency) return null;
    const fromRate = baseRate(fromUnit.currency, rates, baseCurrency);
    const toRate = baseRate(toUnit.currency, rates, baseCurrency);
    if (fromRate === null || toRate === null) return null;
    return ((major * fromRate) / toRate) * toUnit.divisor;
}

/** Misma divisa y misma unidad (GBp ≠ GBP: peniques frente a libras). */
export function sameTargetUnit(a: string | null | undefined, b: string | null | undefined): boolean {
    const ua = chartPriceUnit(a);
    const ub = chartPriceUnit(b);
    return ua !== null && ub !== null && ua.currency === ub.currency && ua.divisor === ub.divisor;
}

/** Etiqueta del objetivo que se queda en su divisa por falta de tipo de cambio. */
export function unconvertedTargetLabel(targetCurrency: string): string {
  const code = targetCurrency.toUpperCase();
  return code === 'USD' ? '(ADR, USD)' : `(en ${code})`;
}
