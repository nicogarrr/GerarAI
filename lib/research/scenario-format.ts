/**
 * Formato de las cifras de escenarios. El backend no manda divisa: se usa la
 * de cotización de la empresa y solo cuando no hay evidencia de ADR (con ADR
 * los estados financieros pueden estar en la divisa del emisor, que no
 * conocemos), en cuyo caso la cifra no se muestra.
 */
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
  // USD: escala inglesa (K/M/B/T); resto de divisas: escala española.
  const locale = currency.code === 'USD' ? 'en-US' : 'es-ES';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency.code,
    notation: 'compact',
    maximumFractionDigits: digits,
    // Compact notation suppresses trailing zeroes by default even for plain
    // currency values. Keep the requested precision below the compact range.
    ...(Math.abs(value) < 1000 ? { minimumFractionDigits: digits } : {}),
  }).format(value);
}
