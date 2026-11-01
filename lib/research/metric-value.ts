// @ts-expect-error explicit extension is needed by node strip-types tests.
import { formatProvenanceValue } from './provenance-format.ts';
// @ts-expect-error TS5097
import { naFor } from '../format.ts';
// @ts-expect-error TS5097
import { createTranslator } from '../i18n/translate.ts';

/** Respect the fact's unit; never substitute the listing's currency or ADS basis. */
export function formatResearchMetric(
  value: number | string | null | undefined,
  unit: string,
  locale: 'es' | 'en' = 'es',
): string {
  const na = naFor(locale);
  if (value == null || value === '') return na;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return na;
  const perShare = /^([A-Z]{3})\/(?:share|shares)$/.exec(unit);
  // Inglés (Ajustes → Idioma): «$3.10/share»; español sin cambios («3,10 US$/acción»).
  const fixedMoney = (currency: string) => new Intl.NumberFormat(locale === 'en' ? 'en-US' : 'es-ES', {
    style: 'currency', currency, useGrouping: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(parsed);
  if (perShare) return createTranslator(locale)('research.metricPerShare', { amount: fixedMoney(perShare[1]) });
  if (/^[A-Z]{3}$/.test(unit) && Math.abs(parsed) < 1e6) return fixedMoney(unit);
  // Unknown storage tokens are not verified units. Do not infer scaling/currency.
  const known = /^[A-Z]{3}$/.test(unit) || ['decimal', 'ratio', 'fraction', '%', 'pct', 'percent', 'percentage', 'shares', 'share', 'pure', 'unitless', 'dimensionless', 'x'].includes(unit.toLowerCase());
  return formatProvenanceValue(parsed, known ? unit : '', locale);
}
