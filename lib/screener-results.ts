import { formatCompact, formatNumber, NA } from '@/lib/format';
import { metricLabel } from '@/lib/research/metric-labels';

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

/** Etiqueta legible de la métrica de un criterio (gross_margin -> Margen bruto). */
export function screenCriterionMetricLabel(metric: string): string {
  return metricLabel(metric);
}

/**
 * Operando derecho del criterio tal como lo escribió el usuario («0.4»):
 * número -> formato es-ES («0,4»); nombre de métrica -> etiqueta legible.
 */
export function formatScreenCriterionRight(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === '') return NA;
  const trimmed = value.trim();
  return Number.isFinite(Number(trimmed))
    ? formatNumber(trimmed, { maximumFractionDigits: 4 })
    : metricLabel(trimmed);
}

/** Campos sin dato (missing_fields) con etiqueta legible, no el slug técnico. */
export function screenMissingFieldsLabel(fields: string[]): string {
  return fields.map((field) => metricLabel(field)).join(', ');
}
