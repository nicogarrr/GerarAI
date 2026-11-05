import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LongTermModelPanel } from '@/components/research/FundamentalModelPanels';
import type { ResearchLongTermModel } from '@/lib/actions/research.actions';

/** Margen FCF proyectado fuera de [-100 %, 100 %] (p. ej. -1546 % en una
 *  pre-ingresos con ingresos casi nulos): la UI muestra N/D con aviso,
 *  nunca la cifra absurda ni el FCF que de ella deriva. */
const forecast = (over: Record<string, unknown>) => ({
  year: 2030,
  revenue: 842_900_000,
  gross_profit: null,
  operating_income: null,
  ebitda: null,
  net_income: null,
  operating_cash_flow: null,
  capital_expenditure: null,
  free_cash_flow: -13_036_000_000,
  working_capital: null,
  working_capital_absorption: null,
  net_debt: null,
  shares_diluted: null,
  fcf_per_share: null,
  fcf_margin: -15.461,
  roic: null,
  scenario: 'base',
  wacc: 0.13,
  evidence: {},
  ...over,
});

const scenario = (point: ReturnType<typeof forecast>) => ({
  probability: 0.5,
  assumptions: {},
  drivers: [],
  forecast: [point],
  year_5: point,
  terminal_year: point,
  revenue_bridge: { status: 'ok' },
  fcf_bridge: { status: 'ok' },
  valuation: null,
});

const model = (over: Record<string, unknown>): ResearchLongTermModel => ({
  ticker: 'ASTS',
  company: 'AST SpaceMobile',
  currency: 'USD',
  status: 'preview_only',
  publishable: false,
  model: 'long-term-fundamental-model-v2',
  model_version: 'long-term-fundamental-model-v2',
  framework: { key: 'pre_revenue', label: 'pre_revenue', primary_question: '', market_opportunity_mode: '', revenue_drivers: ['suscriptores direccionables'], kpis: ['satélites'], unit_economics: [], segment_model: [], binding_constraints: [], active_modules: [] },
  operating_model: { revenue_drivers: [], kpis: [], unit_economics: [], segment_model: [], binding_constraints: [], active_modules: [] },
  horizon_years: 5,
  as_of_period: '2025-12-31:FY',
  current_price: 37.51,
  missing_inputs: ['WACC con fuente trazable'],
  missing_mandatory_drivers: [],
  driver_model: [],
  persistence: { model_version_id: null, version: null, input_fingerprint: null, status: 'preview_only' },
  historical_review: { years_covered: 3, first_year: 2023, last_year: 2025, rows: [] },
  current_snapshot: { period: null, fiscal_year: null, metrics: {} },
  assumptions: {
    revenue_growth: { value: 0.641, unit: 'pct', source_type: 'derived', basis: '', source_fact_ids: [] },
    fcf_margin: { value: -15.461, unit: 'pct', source_type: 'derived', basis: '', source_fact_ids: [] },
    wacc: { value: 0.13, unit: 'pct', source_type: 'model_policy', basis: '', source_fact_ids: [] },
  },
  scenarios: { base: scenario(forecast({})) },
  reverse_dcf: { status: 'missing', missing_inputs: ['WACC'] },
  market_opportunity: {
    status: 'missing', mode: '', primary_question: '',
    top_down: { status: 'missing', market_type: null, tam: { value: null, unit: '', source_fact_ids: [] }, sam: { value: null, unit: '', source_fact_ids: [] }, som: { value: null, unit: '', source_fact_ids: [] }, future_market: { value: null, source_fact_ids: [] }, current_market_share: null, missing_inputs: [] },
    bottom_up: { status: 'missing', value: null, formulas: [], missing_inputs: [] },
    implied_by_valuation: { status: 'missing', conclusion: '', current_market_share: null, prior_market_share: null, base_future_market_share: null, valuation_implied_market_share: null, missing_inputs: [], source_fact_ids: [] },
    market_share: { status: 'missing', conclusion: '', confidence: '', current_market_share: null, prior_market_share: null, base_future_market_share: null, valuation_implied_market_share: null, source_fact_ids: [], missing_inputs: [] },
    constraints: { status: 'missing', binding_constraint: null, severity: '', conclusion: '', framework_constraints: [] },
    verdict: { label: 'unrealistic_without_new_evidence', confidence: '', conclusion: '' },
    missing_inputs: [],
  },
  market_share: { status: 'missing', conclusion: '', confidence: '' },
  management_capital_allocation: { status: 'missing', metrics: {}, conclusion: '', missing_inputs: [] },
  quality_of_growth: { status: 'ok', quality: 'reasonable', revenue_cagr: { value: 0.641 }, fcf_margin_change: { value: null }, share_count_cagr: { value: null }, unavailable_drivers: [], conclusion: '' },
  owner_earnings: { status: 'missing', value: null, formula: '', missing_inputs: [], source_fact_ids: [] },
  capex_analysis: { status: 'missing', total_capex: null, maintenance_capex: null, growth_capex: null },
  timeline: [],
  what_must_be_true: [],
  source_coverage: { coverage_percent: 100, sourced_values: 1, numeric_values: 1, rule: '' },
  limitations: [],
  ...over,
} as unknown as ResearchLongTermModel);

describe('LongTermModelPanel · margen FCF fuera de rango', () => {
  it('margen -1546 % se muestra N/D con aviso, nunca la cifra', () => {
    const html = renderToStaticMarkup(<LongTermModelPanel model={model({})} />);
    expect(html).not.toContain('1546');
    expect(html).toContain('N/D');
    expect(html).toContain('fuera de rango interpretable');
  });

  it('el FCF derivado del margen absurdo también sale N/D (los ingresos se conservan)', () => {
    const html = renderToStaticMarkup(<LongTermModelPanel model={model({})} />);
    expect(html).not.toContain('13 mil M');
    expect(html).toContain('842,9');
  });

  it('margen normalizado en supuestos base también queda N/D', () => {
    const html = renderToStaticMarkup(<LongTermModelPanel model={model({})} />);
    const normalized = html.split('Margen FCF normalizado')[1] ?? '';
    expect(normalized).not.toContain('1546');
    expect(normalized).toContain('N/D');
  });

  it('margen sano (26 %) y su FCF se muestran con normalidad', () => {
    const sane = forecast({ fcf_margin: 0.26, free_cash_flow: 219_000_000 });
    const html = renderToStaticMarkup(
      <LongTermModelPanel model={model({ scenarios: { base: scenario(sane) }, assumptions: { revenue_growth: { value: 0.641, unit: 'pct', source_type: 'derived', basis: '', source_fact_ids: [] }, fcf_margin: { value: 0.26, unit: 'pct', source_type: 'derived', basis: '', source_fact_ids: [] }, wacc: { value: 0.13, unit: 'pct', source_type: 'model_policy', basis: '', source_fact_ids: [] } } })} />,
    );
    expect(html).toContain('26,0');
    expect(html).toContain('219');
    expect(html).not.toContain('fuera de rango interpretable');
  });

  it('la tabla de escenarios (modelo publicable) aplica la misma regla', () => {
    const bear = forecast({ scenario: 'bear', fcf_margin: -15.461, free_cash_flow: -13_036_000_000 });
    const html = renderToStaticMarkup(
      <LongTermModelPanel model={model({ publishable: true, missing_inputs: [], scenarios: { bear: scenario(bear), base: scenario(forecast({})) } })} />,
    );
    expect(html).not.toContain('1546');
    expect(html).not.toContain('13 mil M');
  });

  it('el límite es ±100 %: -100 % se muestra, -101 % ya es N/D', () => {
    const atLimit = forecast({ fcf_margin: -1, free_cash_flow: -842_900_000 });
    const htmlIn = renderToStaticMarkup(<LongTermModelPanel model={model({ scenarios: { base: scenario(atLimit) } })} />);
    expect(htmlIn).toContain('100,0');
    const pastLimit = forecast({ fcf_margin: -1.01, free_cash_flow: -851_000_000 });
    const htmlOut = renderToStaticMarkup(<LongTermModelPanel model={model({ scenarios: { base: scenario(pastLimit) } })} />);
    expect(htmlOut).not.toContain('101,0');
    expect(htmlOut).toContain('N/D');
  });
});
