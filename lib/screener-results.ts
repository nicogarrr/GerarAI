import { formatCompact, formatNumber, NA } from '@/lib/format';

/** Ranking is a metric value, often serialized Decimal, not an ordinal rank. */
export function formatScreenRank(value: string | number | null, formula?: string | null): string {
  if (value === null || value === '' || !Number.isFinite(Number(value))) return NA;
  return formula?.trim() === 'market_cap'
    ? formatCompact(value, { maximumFractionDigits: 2 })
    : formatNumber(value, { maximumFractionDigits: 4 });
}

/** Valor real con el que la empresa cumple el criterio del filtro (Decimal serializado). */
export function formatScreenCriterionValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return NA;
  return formatNumber(value, { maximumFractionDigits: 4 });
}
