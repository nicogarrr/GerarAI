import { formatCompact, formatNumber, naFor } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { metricLabel } from '@/lib/research/metric-labels';

/** Ranking is a metric value, often serialized Decimal, not an ordinal rank. */
export function formatScreenRank(value: string | number | null, formula?: string | null, locale: Locale = DEFAULT_LOCALE): string {
  if (value === null || value === '' || !Number.isFinite(Number(value))) return naFor(locale);
  return formula?.trim() === 'market_cap'
    ? formatCompact(value, { maximumFractionDigits: 2 }, undefined, locale)
    : formatNumber(value, { maximumFractionDigits: 4 }, undefined, locale);
}

/** Valor real con el que la empresa cumple el criterio del filtro (Decimal serializado). */
export function formatScreenCriterionValue(value: string | number | null | undefined, locale: Locale = DEFAULT_LOCALE): string {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return naFor(locale);
  return formatNumber(value, { maximumFractionDigits: 4 }, undefined, locale);
}

/** Etiqueta legible de la métrica de un criterio (gross_margin -> Margen bruto). */
export function screenCriterionMetricLabel(metric: string, locale: Locale = DEFAULT_LOCALE): string {
  return metricLabel(metric, locale);
}

/**
 * Operando derecho del criterio tal como lo escribió el usuario («0.4»):
 * número -> formato es-ES («0,4»); nombre de métrica -> etiqueta legible.
 */
export function formatScreenCriterionRight(value: string | null | undefined, locale: Locale = DEFAULT_LOCALE): string {
  if (value === null || value === undefined || value.trim() === '') return naFor(locale);
  const trimmed = value.trim();
  return Number.isFinite(Number(trimmed))
    ? formatNumber(trimmed, { maximumFractionDigits: 4 }, undefined, locale)
    : metricLabel(trimmed, locale);
}

/** Campos sin dato (missing_fields) con etiqueta legible, no el slug técnico. */
export function screenMissingFieldsLabel(fields: string[], locale: Locale = DEFAULT_LOCALE): string {
  return fields.map((field) => metricLabel(field, locale)).join(', ');
}

/**
 * Entrada del aviso «sin coincidencias por falta de dato»: la métrica con su
 * etiqueta legible (nunca el slug técnico) y el recuento en formato es-ES.
 * La página de filtro guardado mostraba el slug crudo (`wacc`) en este aviso
 * mientras el resto de la pantalla ya usaba etiquetas («WACC»).
 */
export function screenMissingDataEntry(field: string, count: number, companyCount: number, locale: Locale = DEFAULT_LOCALE): string {
  const n = formatNumber(count, { maximumFractionDigits: 0 }, undefined, locale);
  const total = formatNumber(companyCount, { maximumFractionDigits: 0 }, undefined, locale);
  if (locale === 'en') return `${metricLabel(field, locale)} (no data in ${n} of ${total} companies)`;
  return `${metricLabel(field)} (sin dato en ${n} de ${total} empresas)`;
}
