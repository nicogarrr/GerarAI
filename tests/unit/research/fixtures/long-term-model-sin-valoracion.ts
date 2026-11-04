/**
 * Modelo a largo plazo con los 3 escenarios sin valor/acción (mecanismo real
 * medido en UNH/PLTR, tenant5 2026-11-04: forecast presente, acciones
 * diluidas ausentes → DCF omitido). Recortado a lo que LongTermModelPanel
 * lee; publishable/status se sobreescriben en cada test.
 */
import type { ResearchLongTermModel } from '@/lib/actions/research.actions';

const TERMINAL = { year: 2030, revenue: 733949009752, gross_profit: null, operating_income: 61171562164, ebitda: null, net_income: 44111472093, operating_cash_flow: 57065770849, capital_expenditure: -6344127705, free_cash_flow: 50721643144, working_capital: null, working_capital_absorption: null, net_debt: -156810623873, shares_diluted: null, fcf_per_share: null, fcf_margin: 0.0691, roic: 0.2706, invested_capital: null, funding_model: null, segments: {}, evidence: {}, scenario: 'base', wacc: 0.09 };

const scenario = (name: string, blockers: string[]) => ({
  probability: 0.5,
  probability_basis: {},
  assumptions: {},
  drivers: [],
  forecast: [],
  year_5: null,
  terminal_year: { ...TERMINAL, scenario: name },
  revenue_bridge: { status: 'ok', items: [] },
  fcf_bridge: { status: 'ok', items: [] },
  valuation: null,
  valuation_note: 'DCF skipped: missing diluted share count.',
  valuation_blockers: blockers,
});

export const MODELO_SIN_VALORACION = {
  ticker: 'UNH',
  company: 'UnitedHealth',
  currency: 'USD',
  status: 'ok',
  publishable: true,
  model: 'long_term_fundamental',
  model_version: 'long-term-fundamental-model-v2',
  as_of_period: '2025-12-31:FY',
  horizon_years: 5,
  missing_inputs: [],
  source_coverage: { coverage_percent: 100, sourced_values: 149, numeric_values: 149, rule: '' },
  framework: { key: 'x', label: 'salud', primary_question: '', market_opportunity_mode: '', revenue_drivers: [], kpis: [], unit_economics: [] },
  assumptions: {
    revenue_growth: { value: 0.114, fuentes: [] },
    fcf_margin: { value: 0.069, fuentes: [] },
    wacc: { value: 0.073, source_type: 'calculated_metric' },
  },
  scenarios: {
    bear: scenario('bear', ['current_net_debt_missing', 'terminal_shares_missing']),
    base: scenario('base', ['terminal_shares_missing']),
    bull: scenario('bull', ['terminal_shares_missing']),
  },
  owner_earnings: { value: null, status: 'insufficient_data', formula: '', missing_inputs: [] },
  market_opportunity: {
    top_down: { tam: { value: null } },
    bottom_up: { value: null },
    constraints: { binding_constraint: null },
    verdict: { label: 'unknown', conclusion: '', base_revenue_to_binding_capacity: null },
  },
  quality_of_growth: { quality: 'unknown', revenue_cagr: { value: 0.114 }, fcf_margin_change: { value: 0.01 }, conclusion: '' },
  reverse_dcf: { status: 'insufficient_data', missing_inputs: ['net_debt'] },
  what_must_be_true: [],
  timeline: [],
  historical_review: { years_covered: 7, first_year: 2019, last_year: 2025 },
} as unknown as ResearchLongTermModel;
