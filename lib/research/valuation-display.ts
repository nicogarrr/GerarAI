/**
 * Presentación de la valoración del motor (vista «Valoración» de la ficha).
 * Funciones puras y defensivas: la traza del motor es un dict libre; un
 * campo ausente degrada a null (la vista omite la línea), nunca se inventa.
 */
import { formatPercent } from '@/lib/format';

/** Motivos de no publicación en español claro. «traceable_wacc» como blocker
 *  significa que FALTA (el token suelto se leía como «WACC con fuente
 *  trazable», justo lo contrario). */
const BLOCKER_LABELS: Record<string, string> = {
  traceable_wacc: 'WACC sin cálculo trazable',
  forecast_is_not_the_driver: 'el valor terminal es más del 95 % del valor: la previsión a 5 años no es el motor de esta valoración',
  inferred_fcf_margin_target: 'margen FCF objetivo inferido (con fuentes): convergencia de margen orientativa para una empresa en crecimiento, no una valoración final',
};

const BLOCKER_LABELS_EN: Record<string, string> = {
  traceable_wacc: 'WACC without a traceable calculation',
  forecast_is_not_the_driver: 'terminal value is over 95 % of the value: the 5-year forecast is not what drives this valuation',
  inferred_fcf_margin_target: 'inferred FCF margin target (with sources): indicative margin convergence for a growing company, not a final valuation',
};

export function blockerLabel(id: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? BLOCKER_LABELS_EN : BLOCKER_LABELS)[id] ?? id;
}

/** Procedencia del WACC usado por el motor (resolve_rates del backend). */
const WACC_SOURCE_LABELS: Record<string, string> = {
  calculated_metric: 'calculado con insumos trazables',
  inferred_input: 'inferido, con fuentes',
  tag_default: 'tipo por defecto del modelo, sin fuente trazable',
};

export function waccSourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return WACC_SOURCE_LABELS[source] ?? source;
}

type ReverseDcfLike = {
  status?: string;
  required_revenue_growth?: number | null;
  out_of_bounds?: boolean;
  fcf_margin?: number | null;
  wacc?: number | null;
};

// Dos decimales: un margen FCF del 1,07 % no se puede redondear a «1,1 %»
// (el contexto de la cifra es justamente ese segundo decimal).
const pct = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? null : formatPercent(value, { digits: 2 });

/** DCF inverso en una frase; null cuando el motor no devolvió nada que contar. */
export function reverseDcfText(reverse: ReverseDcfLike | null | undefined): string | null {
  if (!reverse || typeof reverse !== 'object') return null;
  const status = reverse.status ?? (reverse.required_revenue_growth != null ? 'ok' : null);
  if (status === 'ok') {
    const growth = pct(reverse.required_revenue_growth);
    if (!growth) return null;
    const margin = pct(reverse.fcf_margin);
    const wacc = pct(reverse.wacc);
    const basis = margin && wacc ? ` (con margen FCF ${margin} y WACC ${wacc})` : '';
    return `El precio del modelo exige un crecimiento de ingresos del ${growth} anual${basis}; no es una previsión, es lo que el precio ya descuenta.`;
  }
  if (status === 'out_of_bounds') {
    return 'DCF inverso fuera de rango: con los supuestos base no existe un crecimiento de ingresos entre el −25 % y el +75 % anual que haga el modelo valer el precio actual, así que no se publica un «crecimiento exigido».';
  }
  if (status === 'not_applicable') {
    return 'DCF inverso no aplicable: con margen FCF ≤ 0 crecer no aumenta el valor (más ingresos queman más caja), así que no hay crecimiento exigido.';
  }
  return null;
}

type TraceLike = {
  scenarios?: unknown;
  periods?: Record<string, string | null> | undefined;
  wacc?: unknown;
  wacc_source?: unknown;
};

function baseAssumptions(trace: TraceLike): { fcf_margin?: unknown; revenue_growth?: unknown } {
  const scenarios = trace.scenarios as Record<string, { definition?: { assumptions?: Record<string, unknown> } }> | undefined;
  return scenarios?.base?.definition?.assumptions ?? {};
}

/** «Supuestos del escenario base: margen FCF 1,07 % (periodo FY2025) ·
 *  crecimiento de ingresos 7 % · WACC 9 % (…)». null si no hay nada que decir. */
export function baseAssumptionsText(trace: TraceLike | null | undefined): string | null {
  if (!trace || typeof trace !== 'object') return null;
  const assumptions = baseAssumptions(trace);
  const parts: string[] = [];
  const margin = typeof assumptions.fcf_margin === 'number' ? pct(assumptions.fcf_margin) : null;
  if (margin) {
    const period = trace.periods?.fcf_margin ?? trace.periods?.free_cash_flow ?? null;
    parts.push(`margen FCF ${margin}${period ? ` (periodo ${period})` : ''}`);
  }
  const growth = typeof assumptions.revenue_growth === 'number' ? pct(assumptions.revenue_growth) : null;
  if (growth) parts.push(`crecimiento de ingresos ${growth}`);
  const waccValue = typeof trace.wacc === 'number' ? pct(trace.wacc) : null;
  if (waccValue) {
    const source = waccSourceLabel(typeof trace.wacc_source === 'string' ? trace.wacc_source : null);
    parts.push(`WACC ${waccValue}${source ? ` (${source})` : ''}`);
  }
  if (parts.length === 0) return null;
  return `Supuestos del escenario base: ${parts.join(' · ')}.`;
}

/** Notas N/D de escenarios (bear/base/bull/expected) en orden estable. */
export function scenarioNotesList(notes: Record<string, string> | null | undefined): string[] {
  if (!notes || typeof notes !== 'object') return [];
  const order = ['bear', 'base', 'bull', 'expected'];
  return order.filter((key) => typeof notes[key] === 'string' && notes[key]).map((key) => notes[key]);
}
