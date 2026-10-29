// @ts-expect-error explicit extension is needed by node strip-types tests.
import { formatProvenanceValue } from './provenance-format.ts';

/** Respect the fact's unit; never substitute the listing's currency or ADS basis. */
export function formatResearchMetric(value: number | string | null | undefined, unit: string): string {
  if (value == null || value === '') return 'N/D';
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return 'N/D';
  const perShare = /^([A-Z]{3})\/(?:share|shares)$/.exec(unit);
  const fixedMoney = (currency: string) => new Intl.NumberFormat('es-ES', {
    style: 'currency', currency, useGrouping: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(parsed);
  if (perShare) return `${fixedMoney(perShare[1])}/acción`;
  if (/^[A-Z]{3}$/.test(unit) && Math.abs(parsed) < 1e6) return fixedMoney(unit);
  // Unknown storage tokens are not verified units. Do not infer scaling/currency.
  const known = /^[A-Z]{3}$/.test(unit) || ['decimal', 'ratio', 'fraction', '%', 'pct', 'percent', 'percentage', 'shares', 'share', 'pure', 'unitless', 'dimensionless', 'x'].includes(unit.toLowerCase());
  return formatProvenanceValue(parsed, known ? unit : '');
}
