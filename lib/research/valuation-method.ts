/**
 * Método del valor razonable cuando es una estimación con método (capex
 * normalizado / DCF multietapa), el aviso 0,2x–5x y el rango de contraste
 * por múltiplos. Todo viene ya calculado del motor: aquí solo se ordena para
 * pintarlo; sin etiqueta, aviso ni rango devuelve null y la ficha no cambia.
 */
export type FairValueRangeComponent = {
  method: string;
  label: string;
  value: number;
  low?: number | null;
  high?: number | null;
};

export type ValuationMethodLike = {
  valuation_label?: string | null;
  valuation_notes?: string[] | null;
  plausibility_warning?: { message_es?: string | null; ratio_to_price?: number | null } | null;
  fair_value_range?: {
    low?: number | null;
    high?: number | null;
    currency?: string | null;
    components?: FairValueRangeComponent[] | null;
  } | null;
  reverse_dcf?: { explanation_es?: string | null } | null;
};

export type ValuationMethodView = {
  label: string | null;
  notes: string[];
  warning: string | null;
  range: { low: number; high: number; currency: string | null; components: FairValueRangeComponent[] } | null;
  priceImplies: string | null;
};

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

export function valuationMethodView(valuation: ValuationMethodLike | null | undefined): ValuationMethodView | null {
  if (!valuation) return null;
  const label = typeof valuation.valuation_label === 'string' && valuation.valuation_label ? valuation.valuation_label : null;
  const notes = (valuation.valuation_notes ?? []).filter((note): note is string => typeof note === 'string' && note.length > 0);
  const warning = typeof valuation.plausibility_warning?.message_es === 'string' ? valuation.plausibility_warning.message_es : null;
  const rawRange = valuation.fair_value_range;
  const components = (rawRange?.components ?? []).filter((item) => item && finite(item.value));
  const range =
    rawRange && finite(rawRange.low) && finite(rawRange.high) && components.length >= 2
      ? { low: rawRange.low, high: rawRange.high, currency: rawRange.currency ?? null, components }
      : null;
  const explanation = valuation.reverse_dcf?.explanation_es;
  const priceImplies = label && typeof explanation === 'string' && explanation ? explanation : null;
  if (!label && !warning && !range) return null;
  return { label, notes, warning, range, priceImplies };
}

/** Fiabilidad histórica del DCF estándar (data-engine app/valuation/track_record.py). */
export type TrackRecordLike = {
  message_es?: string | null;
  message_en?: string | null;
} | null;

/** Una línea: cuánto pesar el número. Solo existe cuando el valor sale del DCF estándar. */
export function trackRecordText(record: TrackRecordLike | undefined, locale: string): string | null {
  if (!record) return null;
  const text = locale === 'en' ? record.message_en ?? record.message_es : record.message_es;
  return typeof text === 'string' && text ? text : null;
}
