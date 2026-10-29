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
  if (!currency || !fair.currency || currency.toUpperCase() !== fair.currency.toUpperCase()) return null;
  return (fair.value - price) / fair.value;
}
