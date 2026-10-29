/**
 * Formato de las cifras de escenarios. El backend no manda divisa: se usa la
 * de cotización de la empresa y solo cuando no hay evidencia de ADR (con ADR
 * los estados financieros pueden estar en la divisa del emisor, que no
 * conocemos), en cuyo caso la cifra no se muestra.
 */
// @ts-expect-error explicit extension is needed by node strip-types tests.
import { formatMoneyCompact } from '../format.ts';

export type ScenarioCurrency = { code: string } | null;

export function scenarioCurrency(
  currency: string | null | undefined,
  adrRatio: number | null | undefined,
): ScenarioCurrency {
  const code = (currency ?? '').trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) return null;
  if (adrRatio != null) return null;
  return { code };
}

export function formatScenarioMoney(
  value: number | null,
  currency: ScenarioCurrency,
  digits: number,
): string | null {
  if (value == null || !Number.isFinite(value) || !currency) return null;
  // Todas las divisas en es-ES (USD incluido, Nico 29-oct-2026). Millones con
  // la escala fija de formatCompact: Intl es-ES pinta 2,5e9 como «2500 M».
  if (Math.abs(value) >= 1e6) return formatMoneyCompact(value, currency.code, { maximumFractionDigits: digits });
  return new Intl.NumberFormat('es-ES', {
    style: 'currency',
    currency: currency.code,
    notation: 'compact',
    maximumFractionDigits: digits,
    // Compact notation suppresses trailing zeroes by default even for plain
    // currency values. Keep the requested precision below the compact range.
    ...(Math.abs(value) < 1000 ? { minimumFractionDigits: digits } : {}),
  }).format(value);
}
