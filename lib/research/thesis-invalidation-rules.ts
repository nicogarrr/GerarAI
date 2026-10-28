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

export function invalidationMetricLabel(metric: string): string {
  if (metric.startsWith(CUSTOM_METRIC_PREFIX)) return metric.slice(CUSTOM_METRIC_PREFIX.length).trim();
  const known = INVALIDATION_METRICS.find((item) => item.value === metric);
  return known ? known.label.replace(' (%)', '').toLowerCase() : metric;
}

/** Número en es-ES con 2 decimales (coma decimal). */
export function formatThresholdEs(value: number, percent: boolean): string {
  const text = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  return percent ? `${text} %` : text;
}

export function describeInvalidationRule(rule: ThesisInvalidationRule): string {
  return `${invalidationMetricLabel(rule.metric)} ${OPERATOR_TEXT[rule.operator] ?? rule.operator} ${formatThresholdEs(
    rule.threshold,
    isPercentMetric(rule.metric),
  )}`;
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
