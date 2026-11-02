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
const MISSING_EN: Record<string, string> = {
  'periodos no comparables': 'periods not comparable',
  'divisas no comparables': 'currencies not comparable',
  'denominador no positivo': 'non-positive denominator',
};

export function healthMissingLabel(raw: string, locale: 'es' | 'en' = 'es'): string {
  const text = raw.trim();
  const dated = /^([a-z][a-z0-9_]*):FY(\d{4})$/.exec(text);
  if (dated) return locale === 'en' ? `${metricLabel(dated[1], 'en')} (FY ${dated[2]})` : `${metricLabel(dated[1])} (ejercicio ${dated[2]})`;
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(text)) return metricLabel(text, locale);
  if (locale === 'en' && MISSING_EN[text]) return MISSING_EN[text];
  return raw;
}

/**
 * Textos fijos en castellano del resumen de valoración (fair_value_service,
 * valuation_summary y financial_health del backend) en inglés para
 * Ajustes → Idioma = English. Lo que no se reconoce pasa tal cual.
 */
const SUMMARY_EN: Record<string, string> = {
  'Sector sin clasificar': 'Unclassified sector',
  'Modelo no aplicable a financieras, REIT o empresas preingresos': 'Model not applicable to financials, REITs or pre-revenue companies',
  'Sin ejercicios anuales con fuente': 'No sourced annual fiscal years',
  'Ejercicio desactualizado o fechas incoherentes': 'Outdated fiscal year or inconsistent dates',
  'Faltan puntos verificables; no se publica un F-score parcial': 'Verifiable points are missing; a partial F-score is not published',
  'Indicadores contables, no recomendación ni probabilidad de quiebra.': 'Accounting indicators, not a recommendation or a probability of bankruptcy.',
  'Modelo fundamental persistido': 'Saved fundamental model',
  'Sin valor justo': 'No fair value',
  'Motor de valoración': 'Valuation engine',
  'Motor de valoración (orientativo)': 'Valuation engine (indicative)',
};

export function valuationSummaryText(text: string, locale: 'es' | 'en' = 'es'): string {
  if (locale !== 'en' || !text) return text;
  if (SUMMARY_EN[text]) return SUMMARY_EN[text];
  const thesis = /^Tesis publicada v(\d+)( \(antigua\))?$/.exec(text);
  if (thesis) return `Published thesis v${thesis[1]}${thesis[2] ? ' (old)' : ''}`;
  return text;
}

/** Señales Piotroski (financial_health.py) por id estable: etiqueta y fórmula en inglés. */
const PIOTROSKI_EN: Record<string, { label: string; formula: string }> = {
  roa: { label: 'Return on assets is positive', formula: 'Net income(t) / Assets(t-1) > 0' },
  cfo: { label: 'Operating cash flow is positive', formula: 'Operating cash flow(t) / Assets(t-1) > 0' },
  delta_roa: { label: 'Return on assets improves', formula: 'ROA(t) > ROA(t-1)  (ROA = Net income / Prior-year assets)' },
  accrual: { label: 'Operating cash exceeds earnings', formula: 'Operating cash flow(t) / Assets(t-1) > ROA(t)' },
  leverage: { label: 'Long-term leverage falls', formula: 'Long-term debt(t) / Average assets(t) < Long-term debt(t-1) / Average assets(t-1)' },
  liquidity: { label: 'Current ratio improves', formula: 'Current assets(t) / Current liabilities(t) > Current assets(t-1) / Current liabilities(t-1)' },
  issuance: { label: 'No common equity issued', formula: 'Common shares issued(t) = 0 (explicit data point)' },
  margin: { label: 'Gross margin improves', formula: 'Gross profit(t) / Revenue(t) > Gross profit(t-1) / Revenue(t-1)' },
  turnover: { label: 'Asset turnover improves', formula: 'Revenue(t) / Assets(t-1) > Revenue(t-1) / Assets(t-2)' },
};

export function piotroskiSignalText(signal: { id: string; label: string; formula: string }, locale: 'es' | 'en' = 'es'): { label: string; formula: string } {
  const en = locale === 'en' ? PIOTROSKI_EN[signal.id] : undefined;
  return en ?? { label: signal.label, formula: signal.formula };
}
