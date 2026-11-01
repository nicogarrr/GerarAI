/**
 * Criterios de invalidación MEDIBLES de la tesis (métrica, operador, umbral).
 *
 * Mismo vocabulario que data-engine/app/services/thesis_invalidation_rules.py:
 * el backend los guarda en la última versión de la tesis y el evaluador de
 * alertas avisa cuando uno se cumple. Funciones puras, sin dependencias de
 * Next, para poder probarlas con node --test.
 */

export type InvalidationOperator = '>' | '<' | '>=' | '<=' | '==' | '!=';

export type ThesisInvalidationRule = {
  metric: string;
  operator: InvalidationOperator;
  threshold: number;
  description?: string | null;
};

export const CUSTOM_METRIC_PREFIX = 'metrica:';

export const INVALIDATION_METRICS: ReadonlyArray<{ value: string; label: string; percent: boolean; hint: string }> = [
  { value: 'precio', label: 'Precio', percent: false, hint: 'Último cierre, en la divisa de cotización.' },
  {
    value: 'margen_seguridad_pct',
    label: 'Margen de seguridad (%)',
    percent: true,
    hint: 'Valor esperado de la tesis frente al precio de hoy. Ej.: < -10 = cotiza un 10 % por encima del valor esperado.',
  },
  {
    value: 'variacion_desde_tesis_pct',
    label: 'Variación desde la tesis (%)',
    percent: true,
    hint: 'Precio de hoy frente al precio con el que se generó la tesis.',
  },
  {
    value: CUSTOM_METRIC_PREFIX,
    label: 'Métrica financiera…',
    percent: false,
    hint: 'Nombre de la métrica calculada (p. ej. roic, gross_margin). Umbral en su unidad: 0,08 = 8 %.',
  },
];

export const INVALIDATION_OPERATORS: ReadonlyArray<{ value: InvalidationOperator; label: string }> = [
  { value: '<', label: '<' },
  { value: '<=', label: '≤' },
  { value: '>', label: '>' },
  { value: '>=', label: '≥' },
  { value: '==', label: '=' },
  { value: '!=', label: '≠' },
];

const OPERATOR_TEXT: Record<string, string> = { '>': '>', '<': '<', '>=': '≥', '<=': '≤', '==': '=', '!=': '≠' };

export function isPercentMetric(metric: string): boolean {
  return INVALIDATION_METRICS.some((item) => item.value === metric && item.percent);
}

/** Etiqueta y ayuda de cada métrica en inglés (Ajustes → Idioma). */
const INVALIDATION_METRICS_EN: Record<string, { label: string; hint: string }> = {
  precio: { label: 'Price', hint: 'Latest close, in the trading currency.' },
  margen_seguridad_pct: {
    label: 'Margin of safety (%)',
    hint: 'Expected value of the thesis vs. today’s price. E.g. < -10 = trading 10% above the expected value.',
  },
  variacion_desde_tesis_pct: {
    label: 'Change since the thesis (%)',
    hint: 'Today’s price vs. the price when the thesis was generated.',
  },
  [CUSTOM_METRIC_PREFIX]: {
    label: 'Financial metric…',
    hint: 'Name of the computed metric (e.g. roic, gross_margin). Threshold in its unit: 0.08 = 8%.',
  },
};

/** Las métricas del selector en el idioma de la interfaz (mismo `value`). */
export function invalidationMetrics(locale: 'es' | 'en' = 'es'): ReadonlyArray<{ value: string; label: string; percent: boolean; hint: string }> {
  if (locale !== 'en') return INVALIDATION_METRICS;
  return INVALIDATION_METRICS.map((item) => ({ ...item, ...(INVALIDATION_METRICS_EN[item.value] ?? {}) }));
}

export function invalidationMetricLabel(metric: string, locale: 'es' | 'en' = 'es'): string {
  if (metric.startsWith(CUSTOM_METRIC_PREFIX)) return metric.slice(CUSTOM_METRIC_PREFIX.length).trim();
  const known = invalidationMetrics(locale).find((item) => item.value === metric);
  return known ? known.label.replace(' (%)', '').toLowerCase() : metric;
}

/** Número en es-ES con 2 decimales (coma decimal). */
export function formatThresholdEs(value: number, percent: boolean): string {
  const text = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  return percent ? `${text} %` : text;
}

/** Número en inglés con 2 decimales (punto decimal, «%» pegado). */
function formatThresholdEn(value: number, percent: boolean): string {
  const text = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false }).format(value);
  return percent ? `${text}%` : text;
}

export function describeInvalidationRule(rule: ThesisInvalidationRule, locale: 'es' | 'en' = 'es'): string {
  const percent = isPercentMetric(rule.metric);
  const threshold = locale === 'en' ? formatThresholdEn(rule.threshold, percent) : formatThresholdEs(rule.threshold, percent);
  return `${invalidationMetricLabel(rule.metric, locale)} ${OPERATOR_TEXT[rule.operator] ?? rule.operator} ${threshold}`;
}

/** Acepta coma o punto decimal ("−10,5", "0.08"). null si no es un número finito. */
export function parseThreshold(raw: string): number | null {
  const cleaned = raw.trim().replace(/\u2212/g, '-').replace(/\s/g, '').replace(',', '.');
  if (!/^[-+]?\d+(\.\d+)?$/.test(cleaned)) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

/** Normaliza lo que devuelve la API (lista JSON sin tipar) a reglas válidas. */
export function coerceInvalidationRules(raw: unknown): ThesisInvalidationRule[] {
  if (!Array.isArray(raw)) return [];
  const rules: ThesisInvalidationRule[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const record = item as Record<string, unknown>;
    const operator = String(record.operator ?? '');
    const threshold = typeof record.threshold === 'number' ? record.threshold : parseThreshold(String(record.threshold ?? ''));
    if (typeof record.metric !== 'string' || !Object.hasOwn(OPERATOR_TEXT, operator) || threshold === null) continue;
    rules.push({
      metric: record.metric,
      operator: operator as InvalidationOperator,
      threshold,
      description: typeof record.description === 'string' ? record.description : null,
    });
  }
  return rules;
}
