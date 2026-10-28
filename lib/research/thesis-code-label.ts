// @ts-expect-error Explicit TS extension for strip-types guards.
import { frameworkTerm } from './framework-terms.ts';
// @ts-expect-error Explicit TS extension for strip-types guards.
import { METRIC_LABELS } from './metric-labels.ts';

/** Only known standalone identifiers. Never rewrite code blocks, URLs or prose. */
export function thesisCodeLabel(value: string): string {
  const labels: Record<string, string> = {
    insufficient_data: 'datos insuficientes', unknown: 'sin determinar',
    unassigned: 'sin asignar', preview_only: 'solo vista previa',
    fact_anchored_sensitivity: 'sensibilidad anclada a datos',
    'n/a': 'no disponible', fiscal_year: 'ejercicio fiscal',
    free_cash_flow_or_fcf_margin: 'flujo de caja libre o margen FCF',
    normalized_fcf_margin: 'margen FCF normalizado',
    revenue_history_two_periods: 'ingresos reportados de dos periodos',
    traceable_wacc: 'WACC trazable', draft: 'borrador',
    draft_failed_audit: 'borrador sin auditoría superada',
    estimacion_llm: 'estimación del modelo',
  };
  if (!/^[a-z][a-z0-9_/]*$/.test(value)) return value;
  return (Object.hasOwn(labels, value) ? labels[value] : null) ?? (Object.hasOwn(METRIC_LABELS, value) ? METRIC_LABELS[value] : null) ?? frameworkTerm(value) ?? value;
}
