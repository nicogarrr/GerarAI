// @ts-expect-error explicit extension is needed by node strip-types tests.
import { formatProvenanceValue, formatMoneyShort } from './provenance-format.ts';

/** Respect the fact's unit; never substitute the listing's currency or ADS basis. */
export function formatResearchMetric(value: number | string | null | undefined, unit: string): string {
  if (value == null || value === '') return 'N/D';
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return 'N/D';
  const perShare = /^([A-Z]{3})\/(?:share|shares)$/.exec(unit);
  if (perShare) return `${formatMoneyShort(parsed, perShare[1])}/acción`;
  return formatProvenanceValue(parsed, unit);
}
