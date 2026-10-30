import { chartPriceUnit } from '@/lib/market/chart-price-units';
import { metricLabel } from '@/lib/research/metric-labels';

export type HealthEvidence = { fact_id: number; metric: string; value: number; unit: string; period_end: string; source_url: string; source_type: string };
export type FinancialHealth = {
  status: string; reason?: string; period_end?: string; notice: string;
  piotroski: { score: number | null; evaluated: number; total: number; methodology_url: string; signals: { id: string; label: string; formula: string; point: number | null; missing_input: string | null; evidence: HealthEvidence[] }[] };
  altman: { status: string; score: number | null; variant: string; reason?: string; methodology_url: string; evidence?: HealthEvidence[] };
};
export type ValuationSummary = {
  ticker: string;
  fair_value: { value: number | null; currency: string | null; label: string; as_of: string | null; publishable: boolean; stale: boolean };
  reverse_dcf: { status: string; required_revenue_growth: number | null; as_of: string | null; source: string; market_price: number | null; model_version_id: number | null };
  health: FinancialHealth;
};

/** Margin of safety is the discount to VALUE, not upside divided by price. */
export function safetyMargin(price: number | null, currency: string | null, fair: ValuationSummary['fair_value']): number | null {
  if (!fair.publishable || !fair.value || !Number.isFinite(fair.value) || fair.value <= 0 || price == null || !Number.isFinite(price) || price <= 0) return null;
  // Unidad, no solo divisa: «GBp» (peniques) no es «GBP». Comparar en
  // mayúsculas igualaba 1.500 p con un valor justo de 15 £ (margen −9.900 %).
  // El precio se pasa a la unidad mayor; el valor justo debe venir ya en ella.
  const quoteUnit = chartPriceUnit(currency);
  const fairUnit = chartPriceUnit(fair.currency);
  if (!quoteUnit || !fairUnit || fairUnit.divisor !== 1 || quoteUnit.currency !== fairUnit.currency) return null;
  const major = price / quoteUnit.divisor;
  return (fair.value - major) / fair.value;
}

/**
 * El backend (financial_health.py) señala el dato que falta como «métrica:FYaaaa»
 * («total_assets:FY2024»). Se muestra con la etiqueta española y el ejercicio;
 * los motivos que ya vienen redactados («periodos no comparables») pasan tal cual.
 */
export function healthMissingLabel(raw: string): string {
  const text = raw.trim();
  const dated = /^([a-z][a-z0-9_]*):FY(\d{4})$/.exec(text);
  if (dated) return `${metricLabel(dated[1])} (ejercicio ${dated[2]})`;
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(text)) return metricLabel(text);
  return raw;
}
