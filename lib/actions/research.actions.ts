'use server';

import { isQuoteLandingEvent } from '@/lib/news-landing';
import { BACKEND_PAGE_SIZE, fetchAllBackendPages, type PaginatedBackendResponse } from '@/lib/paginated-backend';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { revalidatePath } from 'next/cache';
import { AppError, ExternalAPIError, ValidationError, getSafeErrorMessage } from '@/lib/types/errors';
import { sourcesPageInfo } from '@/lib/research/sources-inventory';
import { researchRequest } from '@/lib/research/client';
import { paginateAll } from '@/lib/paginate-all';
import type { components } from '@/lib/research/openapi.generated';
import type { JournalFairValue, JournalTrade } from '@/lib/research/journal-trade';
import type { ResearchTtm } from '@/lib/research/ttm-display';


type ResearchCompany = {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  industry: string;
  company_type: string;
  valuation_model: string;
  factor_tags: string[];
  special_sources: string[];
  special_risks: string[];
};

type ResearchWorkflow = {
  name: string;
  input: string;
  steps: string[];
  execution_mode?: string;
  implementation_status?: 'implemented' | 'partial' | 'descriptive';
  truth?: string;
};

type ResearchSettings = {
  app_env: string;
  maf_version: string;
  budget: {
    daily_cost_eur: number;
    monthly_cost_eur: number;
    daily_cap_eur: number;
    monthly_cap_eur: number;
  };
  connectors: Record<string, boolean | string>;
  llm: {
    provider: string;
    configured: boolean;
    model: string | null;
    reason?: string;
  };
};

export type ResearchFact = {
  id: number;
  company_id: number;
  metric: string;
  value: string;
  unit: string;
  period: string;
  fiscal_year: number | null;
  fiscal_quarter: string | null;
  source_id: number | null;
  source_type: string;
  is_reported: boolean;
  is_adjusted: boolean;
  confidence: string;
  created_at: string;
  // Procedencia enlazable (documento de origen del dato, p. ej. filing SEC).
  // Nulos cuando el hecho no tiene documento: se muestra la fuente como
  // texto plano, nunca un enlace inventado.
  source_url?: string | null;
  source_title?: string | null;
  source_published_at?: string | null;
};

export type ResearchCalculatedMetric = {
  id: number | null;
  company_id: number | null;
  metric: string;
  value: string | null;
  unit: string;
  period: string;
  fiscal_year: number | null;
  fiscal_quarter: string | null;
  status: string;
  definition_version: string;
  formula: string;
  numerator: string | null;
  denominator: string | null;
  source_fact_ids: number[];
  calculation_trace: Record<string, unknown>;
  confidence: string;
};

type ResearchPeerComparison = {
  ticker: string;
  basis: string;
  selection_trace?: Record<string, unknown>;
  peer_count: number;
  peer_count_selected?: number;
  peers_without_data?: string[];
  min_peer_sample?: number;
  metrics: string[];
  benchmarks: Record<
    string,
    {
      peer_median: string | null;
      peer_average: string | null;
      peer_sample_size: number;
      insufficient_sample?: boolean;
      note?: string | null;
      // F153: valores atipicos etiquetados por el motor - visibles con su
      // etiqueta, excluidos de la mediana/promedio.
      excluded_atypical?: Array<{ ticker: string; value: string | null; atypical: string | null }>;
      target_value: string | null;
      target_atypical?: string | null;
      target_vs_peer_median: string | null;
    }
  >;
  companies: Array<{
    ticker: string;
    name: string;
    sector: string;
    industry: string;
    is_target: boolean;
    metrics: Record<
      string,
      {
        value: string | null;
        status: string;
        unit: string;
        period: string;
        confidence: string;
        source_fact_ids: number[];
        atypical?: string | null;
      }
    >;
  }>;
};

export type ResearchValuation = {
  ticker: string;
  model_type: string;
  status?: string;
  publishable?: boolean;
  current_price: number | null;
  bear_value: number | null;
  base_value: number | null;
  bull_value: number | null;
  expected_value: number | null;
  margin_of_safety: number | null;
  missing_inputs?: string[];
  adr_ratio?: number | null;
  value_per_share_basis?: string | null;
  listed_share_values?: Partial<Record<'bear' | 'base' | 'bull' | 'expected', number | null>> | null;
  /** Escenarios N/D (valor por acción <= 0): motivo en español, uno por escenario. */
  scenario_notes?: Record<string, string> | null;
  reverse_dcf: {
    status?: string;
    out_of_bounds?: boolean;
    reason?: string;
    required_revenue_growth?: number;
    solved_value_per_share?: number;
    fcf_margin?: number | null;
    wacc?: number | null;
    trace?: Record<string, unknown>;
  };
  sensitivity: {
    rows?: Array<{
      revenue_growth: number;
      values: Array<{ wacc: number; value_per_share: number }>;
    }>;
    trace?: Record<string, unknown>;
  };
  moat?: Record<string, unknown>;
  trace: {
    method?: string;
    engine?: string;
    input_source?: string;
    fact_ids?: Record<string, number | null>;
    periods?: Record<string, string | null>;
    bootstrap_notice?: string;
    missing_inputs?: string[];
    publishable?: boolean;
    status?: string;
    notice?: string;
    [key: string]: unknown;
  };
};

type ResearchThesisCatalyst = {
  label?: string;
  date?: string;
  time?: string;
  eps_forecast?: number;
  source?: string;
};

export type ResearchThesis = {
  id: number;
  company_id: number;
  version: number;
  status: string;
  thesis_markdown: string;
  executive_summary: string;
  narrative_sections?: { titulo: string; parrafos: string[] }[] | null;
  rating: string;
  current_price: string | null;
  bear_value: string | null;
  base_value: string | null;
  bull_value: string | null;
  expected_value: string | null;
  margin_of_safety: string | null;
  archived_margin_of_safety?: string | null;
  margin_of_safety_convention?: string | null;
  margin_of_safety_status?: string;
  data_confidence_score: number;
  source_coverage_score: number;
  red_team_score: number;
  valuation_risk_score: number;
  hypothesis?: string | null;
  catalysts?: ResearchThesisCatalyst[] | null;
  invalidation_criteria?: string[] | null;
  /** Criterios MEDIBLES (métrica, operador, umbral) que vigila el evaluador de
   *  alertas; null = sin criterios medibles. */
  invalidation_rules?: Array<{ metric: string; operator: string; threshold: number; description?: string | null }> | null;
  scenario_probabilities?: Record<string, number> | null;
  /** Human-in-the-loop: inputs que faltan para completar la tesis (nunca se
   *  inventan; la app los pide). null = sin informacion. */
  missing_inputs?: string[] | null;
  /** Procedencia de cada input del modelo: dato (cita) / derivado (formula +
   *  inputs) / estimacion_llm (metodo + confianza) / supuesto (rationale). */
  inputs_provenance?: Array<{
    key: string;
    label: 'dato' | 'derivado' | 'estimacion_llm' | 'supuesto';
    value: number | string | null;
    unit?: string | null;
    method?: string | null;
    source_fact_ids?: number[];
    confidence?: number | null;
    /** OFICIAL = fuente primaria verificada (URL + fecha); INFERIDO = estimación con base. */
    origen?: 'OFICIAL' | 'INFERIDO';
    fuentes?: Array<{ fact_id: number; url: string | null; fecha: string | null; titulo: string | null; oficial: boolean }>;
    base_inferencia?: string | null;
    urls_inferencia?: string[];
    base_documentada?: boolean;
  }> | null;
  /** Base por acción de los escenarios al generar la tesis; null/ausente = tesis anterior sin evidencia. */
  valuation_basis?: {
    margin_of_safety_convention?: string | null;
    /** Fecha (ISO) de la cotización que usó el modelo al generar la versión;
     *  null/ausente = sin fecha conocida: el precio se rotula sin fecha. */
    price_as_of?: string | null;
    value_per_share_basis?: string | null;
    adr_ratio?: number | null;
    listed_share_values?: Partial<Record<'bear' | 'base' | 'bull' | 'expected', number>> | null;
  } | null;
  stale?: boolean;
  latest_data_at?: string | null;
  created_at: string;
};

type ResearchThesisHistoryEntry = {
  id: number;
  version: number;
  status: string;
  rating: string;
  red_team_score: number;
  data_confidence_score: number;
  created_at: string;
  updated_at: string;
  diff: {
    change_summary: string;
    affected_assumptions: string[];
    rating_changed: boolean;
    created_at: string;
  } | null;
};

type ResearchSourceDocument = {
  id: number;
  ticker: string | null;
  title: string;
  source_type: string;
  source_tier: string;
  source_url: string | null;
  storage_uri?: string | null;
  checksum?: string | null;
  metadata?: Record<string, unknown>;
  published_at: string | null;
  chunks?: ResearchSourceChunk[];
};

type ResearchSourceChunk = {
  id: number;
  document_id: number;
  chunk_index: number;
  text: string;
  token_count: number;
  metadata?: Record<string, unknown>;
};

export type ResearchSourceAudit = {
  id: number;
  thesis_version_id: number | null;
  thesis_version?: number | null;
  created_at?: string | null;
  passed: boolean;
  source_coverage_score: number;
  unsupported_claims: string[];
  weak_claims: string[];
  data_conflicts: string[];
  required_fixes: string[];
};

type ResearchClaimEvidence = {
  id: number;
  claim_id: number;
  document_id: number | null;
  document_chunk_id: number | null;
  evidence_type: string;
  summary: string;
  source_url: string | null;
  source_tier: string;
  confidence: string;
  created_at: string;
};

type ResearchClaim = {
  id: number;
  company_id: number | null;
  thesis_version_id: number | null;
  statement: string;
  claim_type: string;
  status: string;
  confidence: string;
  materiality_score: number;
  source_quality: string;
  evidence: ResearchClaimEvidence[];
  created_at: string;
};

type ResearchThesisSection = {
  id: number;
  thesis_version_id: number;
  company_id: number;
  section_key: string;
  title: string;
  body: string;
  status: string;
  order_index: number;
  confidence: string;
  updated_at: string;
};

export type ResearchThesisChange = {
  id: number;
  company_id: number | null;
  from_version_id: number | null;
  to_version_id: number | null;
  change_type: string;
  impact_direction: 'positive' | 'negative' | 'neutral' | 'mixed' | string;
  materiality_score: number;
  summary: string;
  affected_claim_ids: number[];
  affected_metrics: string[];
  requires_review: boolean;
  created_at: string;
  updated_at: string;
};
export type ResearchChatResponse = {
  answer: string;
  sections: Array<{
    key: 'facts' | 'calculations' | 'user_hypotheses' | 'inferences' | 'contradictions' | 'insufficient_data' | 'conclusion';
    body: string;
    citations: string[];
  }>;
  sources: Array<{
    type: string;
    id: number | string | null;
    title: string;
    [key: string]: unknown;
  }>;
  blocked: boolean;
  proposed_actions: string[];
  evidence_suggestions: ResearchEvidenceSuggestion[];
  prompt_version?: string | null;
  model?: string | null;
};

type ResearchEvidenceSuggestion = {
  id: number;
  company_id: number | null;
  document_id: number | null;
  document_chunk_id: number | null;
  suggested_claim_id: number | null;
  suggestion_type: string;
  statement: string;
  relation: string;
  rationale: string;
  quote: string | null;
  confidence: string;
  status: string;
  prompt_version: string;
  metadata_: Record<string, unknown>;
  created_at: string;
};

type ResearchReview = {
  id: number;
  company_id: number | null;
  review_type: string;
  status: string;
  priority: string;
  title: string;
  summary: string;
  thesis_change_id: number | null;
  claim_id: number | null;
  news_event_id: number | null;
  created_at: string;
};

type ResearchAlert = {
  id: number;
  company_id: number | null;
  review_id: number | null;
  severity: string;
  status: string;
  alert_type: string;
  title: string;
  message: string;
  channels: string[];
  snoozed_until: string | null;
  created_at: string;
  // URL ya validada por el backend (http/https con host); la UI la vuelve a validar.
  source_url?: string | null;
};

type ResearchThesisGraph = {
  ticker: string;
  thesis_version_id: number;
  nodes: Array<{
    id: number;
    node_key: string;
    node_type: string;
    label: string;
    description: string;
    status: string;
    confidence: string;
    materiality_score: number;
    claim_ids: number[];
    invalidation_conditions: string[];
  }>;
  edges: Array<{
    id: number;
    from_node_id: number;
    to_node_id: number;
    edge_type: string;
    strength: string;
  }>;
};

type ResearchPeerAnalysis = {
  ticker: string;
  status: string;
  selection: {
    basis: string;
    trace: Record<string, unknown>;
    peers: string[];
  };
  advantages: Array<Record<string, unknown>>;
  disadvantages: Array<Record<string, unknown>>;
  insufficient_data: string[];
  methodology: string;
};

export type ResearchMoat = {
  qualitative_checklist?: Array<{ id: string; question: string; status: string; excerpts: Array<{ quote: string; source_url: string; source_title: string; relation: string; published_at: string | null }> }>; 
  ticker: string;
  status: string;
  methodology: string;
  nico_mapping?: { version: string; types: Record<string, string>; mapping: Record<string, string>; unclassified: string[] };
  moats: Array<{
    type: string;
    nico_classification?: { type: string | null; label: string; method: string; basis: string };
    strength: number;
    trend: string;
    persistence: string;
    confidence: number;
    status: string;
    supporting_claim_ids: number[];
    contradicting_claim_ids: number[];
  }>;
};

type ResearchRedTeam = {
  id: number;
  score: number;
  status: string;
  strongest_bear_case: string;
  findings: Array<{
    severity: string;
    type: string;
    message: string;
    trace: Record<string, unknown>;
  }>;
  broken_assumptions: string[];
  missing_risks: string[];
  falsification_tests: string[];
  created_at: string;
};

type ResearchLongTermForecast = {
  year: number;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  ebitda: number | null;
  net_income: number | null;
  operating_cash_flow: number | null;
  capital_expenditure: number | null;
  free_cash_flow: number | null;
  working_capital: number | null;
  working_capital_absorption: number | null;
  net_debt: number | null;
  shares_diluted: number | null;
  fcf_per_share: number | null;
  fcf_margin: number | null;
  roic: number | null;
  scenario: string;
  wacc: number;
  evidence: Record<string, { source_fact_ids: number[]; calculation: string }>;
};

type ResearchLongTermScenario = {
  probability: number;
  assumptions: Record<string, { value: number | null; unit: string; source_type: string; basis: string; source_fact_ids: number[]; fuentes?: Array<{ fact_id: number; titulo: string | null; url: string | null; fecha: string | null }> }>;
  drivers: string[];
  forecast: ResearchLongTermForecast[];
  year_5: ResearchLongTermForecast | null;
  terminal_year: ResearchLongTermForecast | null;
  revenue_bridge: { status: string; items?: Array<{ label: string; value: number | null; source_fact_ids: number[]; note?: string }>; unavailable_drivers?: string[] };
  fcf_bridge: { status: string; items?: Array<{ label: string; value: number | null; source_fact_ids: number[] }>; unavailable_drivers?: string[] };
  valuation: { value_per_share: number; enterprise_value: number; equity_value: number } | null;
};

export type ResearchLongTermModel = {
  ticker: string;
  company: string;
  currency: string;
  status: string;
  publishable: boolean;
  model: string;
  model_version: string;
  framework: {
    key: string;
    label: string;
    primary_question: string;
    market_opportunity_mode: string;
    revenue_drivers: string[];
    kpis: string[];
    unit_economics: string[];
    segment_model: string[];
    binding_constraints: string[];
    active_modules: string[];
  };
  operating_model: {
    revenue_drivers: string[];
    kpis: string[];
    unit_economics: string[];
    segment_model: string[];
    binding_constraints: string[];
    active_modules: string[];
  };
  horizon_years: number;
  as_of_period: string | null;
  current_price: number | null;
  missing_inputs: string[];
  missing_mandatory_drivers: string[];
  driver_model: Array<{
    key: string;
    driver_type: 'revenue_driver' | 'kpi';
    required: boolean;
    status: 'sourced' | 'derived' | 'missing';
    value: number | null;
    unit: string;
    confidence: number;
    source_fact_ids: number[];
  }>;
  persistence: {
    model_version_id: number | null;
    version: number | null;
    input_fingerprint: string | null;
    status: string;
  };
  historical_review: { years_covered: number; first_year: number | null; last_year: number | null; rows: Array<Record<string, unknown>> };
  current_snapshot: { period: string | null; fiscal_year: number | null; metrics: Record<string, { value: number | null; source_fact_ids: number[]; status: string }> };
  assumptions: Record<string, { value: number | null; unit: string; source_type: string; basis: string; source_fact_ids: number[]; fuentes?: Array<{ fact_id: number; titulo: string | null; url: string | null; fecha: string | null }>; confidence: number }>;
  scenarios: Record<string, ResearchLongTermScenario>;
  reverse_dcf: { status: string; required_revenue_growth?: number; base_revenue_growth?: number; fcf_margin?: number | null; growth_gap_vs_base?: number; market_price?: number | null; missing_inputs?: string[] };
  market_opportunity: {
    status: string;
    mode: string;
    primary_question: string;
    top_down: {
      status: string;
      market_type: string | null;
      tam: { value: number | null; unit: string; source_fact_ids: number[] };
      sam: { value: number | null; unit: string; source_fact_ids: number[] };
      som: { value: number | null; unit: string; source_fact_ids: number[] };
      future_market: { value: number | null; source_fact_ids: number[] };
      current_market_share: number | null;
      missing_inputs: string[];
    };
    bottom_up: { status: string; value: number | null; formulas: Array<{ label: string; value: number | null; unit?: string | null; status: string; missing_inputs?: string[]; source_fact_ids: number[] }>; missing_inputs: string[] };
    implied_by_valuation: { status: string; conclusion: string; current_market_share: number | null; prior_market_share: number | null; base_future_market_share: number | null; valuation_implied_market_share: number | null; missing_inputs: string[]; source_fact_ids: number[] };
    market_share: { status: string; conclusion: string; confidence: string; current_market_share: number | null; prior_market_share: number | null; base_future_market_share: number | null; valuation_implied_market_share: number | null; source_fact_ids: number[]; missing_inputs: string[] };
    constraints: { status: string; binding_constraint: string | null; severity: string; conclusion: string; framework_constraints: string[] };
    verdict: { label: string; confidence: string; conclusion: string; base_revenue_to_binding_capacity?: number };
    missing_inputs: string[];
  };
  market_share: { status: string; conclusion: string; confidence: string; current_market_share?: number; prior_market_share?: number | null; implied_future_market_share?: number | null; missing_inputs?: string[] };
  management_capital_allocation: { status: string; metrics: Record<string, { value: number | null; unit: string; status: string; source_fact_ids: number[]; calculation?: string; note?: string }>; conclusion: string; missing_inputs: string[] };
  quality_of_growth: { status: string; quality: string; revenue_cagr: { value: number | null }; fcf_margin_change: { value: number | null }; share_count_cagr: { value: number | null }; unavailable_drivers: string[]; conclusion: string };
  owner_earnings: { status: string; value: number | null; formula: string; missing_inputs?: string[]; source_fact_ids: number[] };
  capex_analysis: { status: string; total_capex: number | null; maintenance_capex: number | null; growth_capex: number | null; missing_inputs?: string[]; maintenance_vs_growth?: string };
  timeline: Array<{ date: string | null; type: string; title: string; source: string; thesis_impact: string; source_url?: string | null }>;
  what_must_be_true: Array<{ id: string; condition: string; value: number | null; unit: string; source_fact_ids: number[]; status: string; comparison?: number | null }>;
  source_coverage: { coverage_percent: number; sourced_values: number; numeric_values: number; rule: string };
  limitations: string[];
};

export type ResearchDecisionJournalEntry = {
  id: number;
  thesis_version_id: number | null;
  model_version_id: number | null;
  decision_date: string;
  decision: string;
  rationale: string;
  what_must_be_true: string[];
  price: number | null;
  status: string;
  metadata: Record<string, unknown>;
  /** Operación real (compra/venta IBKR o manual) que ejecutó la decisión. */
  transaction_id?: number | null;
  transaction?: JournalTrade | null;
  /** Valor justo vigente el día de la operación (point-in-time). */
  fair_value_on_day?: JournalFairValue | null;
};

export type ResearchExpectationReview = {
  id: number;
  model_version_id: number;
  forecast_id: number;
  actual_fact_id: number | null;
  fiscal_year: number;
  metric: string;
  expected_value: number;
  actual_value: number | null;
  variance: number | null;
  variance_percent: number | null;
  status: string;
  reviewed_at: string | null;
};

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    // Todas las lecturas de research pasan por el cliente común: mismo timeout,
    // mensaje de reintento y caché/ deduplicación para evitar requests colgados.
    return await researchRequest<T>(path, { cache: 'no-store' });
  } catch (error) {
    // 404 es un estado vacío válido para un recurso opcional; no debe
    // convertirse en una caída de la página.
    if (error instanceof AppError && error.statusCode === 404) return fallback;
    if (error instanceof AppError) throw error;
    throw new ExternalAPIError(
      `Research API request failed: ${path}; reintenta en unos segundos.`,
      'research-api',
      error,
    );
  }
}

async function postJson<T>(path: string, fallback: T, body?: unknown): Promise<T> {
  try {
    const requestBody = body ? JSON.stringify(body) : undefined;
    const data = await researchRequest<T>(path, {
      method: 'POST',
      body: requestBody,
      cache: 'no-store',
    });
    return data === undefined ? fallback : data;
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw new ExternalAPIError(`Research API mutation failed: ${path}`, 'research-api', error);
  }
}

async function postForm<T>(path: string, fallback: T, body: FormData): Promise<T> {
  try {
    const data = await researchRequest<T>(path, {
      method: 'POST',
      body,
      cache: 'no-store',
    });
    return data === undefined ? fallback : data;
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw new ExternalAPIError(`Research API upload failed: ${path}`, 'research-api', error);
  }
}


/**
 * `/api/companies` devuelve como mucho COMPANIES_PAGE_SIZE fichas por llamada
 * (tope del backend) y por defecto solo 100. El índice de /research se titula
 * «Todas las empresas con research en GerarAI», así que hay que pedir TODAS las
 * páginas: con la llamada por defecto el índice se cortaba en silencio en la
 * centésima (A→AMBA) y cualquier ticker posterior no aparecía pese a tener
 * ficha. Paginamos hasta recibir una página corta.
 */
const COMPANIES_PAGE_SIZE = 500;

async function getAllResearchCompanies(): Promise<ResearchCompany[]> {
  // paginateAll pide las páginas en oleadas paralelas (ver lib/paginate-all.ts):
  // con ~2.100 fichas el índice deja de esperar 5 páginas en cadena.
  return paginateAll(
    (offset) =>
      getJson<ResearchCompany[]>(
        `/api/companies?limit=${COMPANIES_PAGE_SIZE}&offset=${offset}`,
        [],
      ),
    COMPANIES_PAGE_SIZE,
    (company) => company.ticker,
  );
}

export async function getResearchWorkflows(): Promise<ResearchWorkflow[]> {
  const payload = await getJson<{ workflows: ResearchWorkflow[] }>('/api/workflows', {
    workflows: [],
  });
  return payload.workflows;
}

export async function getResearchSettings(): Promise<ResearchSettings> {
  return getJson<ResearchSettings>('/api/settings', {
    app_env: 'unknown',
    maf_version: 'not loaded',
    budget: {
      daily_cost_eur: 0,
      monthly_cost_eur: 0,
      daily_cap_eur: 0,
      monthly_cap_eur: 0,
    },
    connectors: {},
    llm: { provider: 'unknown', configured: false, model: null, reason: 'backend_unreachable' },
  });
}

/**
 * Dashboard completo del ÍNDICE de /research: es la única pantalla que lista
 * empresas. Las subrutas (workflows, settings) usan las acciones ligeras de
 * arriba: cargar aquí las miles de fichas de empresa para no usarlas sería
 * trabajo y latencia regalados en cada visita.
 */
export async function getResearchDashboard() {
  // Solo lo que el índice materializa: el registro completo y los tickers
  // con tesis. Antes pedía también /api/portfolio/summary (duplicada: la
  // página ya la lee para el orden por relevancia), /api/workflows y
  // /api/settings sin que ninguna tarjeta los usara: latencia y carga de
  // backend regaladas en cada visita.
  const [companies, thesisTickers] = await Promise.all([
    getAllResearchCompanies(),
    getResearchThesisTickers(),
  ]);

  return {
    companies,
    thesisTickers,
  };
}

/**
 * Tickers con tesis en UNA query DISTINCT del backend (bucket «tesis» del
 * orden del índice). null = lectura fallida: el índice degrada ese bucket
 * (nunca afirma tesis inexistentes) y el resto de la página sigue igual.
 * Un backend antiguo sin el endpoint (skew de despliegue) responde 404 y
 * degrada igual.
 */
export async function getResearchThesisTickers(): Promise<string[] | null> {
  try {
    const payload = await getJson<{ tickers: string[] }>('/api/companies/thesis-tickers', {
      tickers: [],
    });
    return payload.tickers;
  } catch {
    return null;
  }
}
type ResearchCompanySnapshot = components['schemas']['CompanySnapshotOut'];

export async function getResearchCompanySnapshot(
  ticker: string,
): Promise<ResearchCompanySnapshot | null> {
  const normalizedTicker = ticker.trim().toUpperCase();
  try {
    // El snapshot usa el mismo cliente y timeout que el resto de research.
    return await researchRequest<ResearchCompanySnapshot>(
      `/api/companies/${encodeURIComponent(normalizedTicker)}/snapshot`,
      { fast: true, cache: 'no-store' },
    );
  } catch (error) {
    // 404 = compañía ausente del master (resolve_company): una empresa del
    // master sin research recibe snapshot construido. Cualquier otro fallo
    // (red, 5xx, firma) se propaga: null tiene procedencia exacta.
    if (error instanceof AppError && error.statusCode === 404) return null;
    throw error;
  }
}

type ResearchCompanySnapshotsBatch = components['schemas']['CompanySnapshotsBatchOut'];

/**
 * Snapshots de varias empresas en UNA llamada (indice de research).
 *
 * Sustituye al fan-out de ~40 GET /{ticker}/snapshot por visita: el
 * backend agrega las queries por IN(company_ids). Los tickers sin
 * company en el registro vuelven en `missing` (nunca snapshots
 * fabricados); ante un fallo de la llamada el indice degrada todas las
 * tarjetas a "no legible", nunca a datos inventados.
 */
export async function getResearchCompanySnapshots(
  tickers: string[],
): Promise<ResearchCompanySnapshotsBatch> {
  const normalized = tickers.map((ticker) => ticker.trim().toUpperCase()).filter(Boolean);
  const query = encodeURIComponent(normalized.join(','));
  return researchRequest<ResearchCompanySnapshotsBatch>(
    `/api/companies/snapshots?tickers=${query}`,
    { fast: true, cache: 'no-store' },
  );
}

type CalculatedMetricsResponse = components['schemas']['CalculatedMetricsResponse'];
export type MoatScoreMetric = components['schemas']['CalculatedMetricOut'];

/**
 * Score del marco de calidad (MOAT V2) persistido para la empresa.
 * null cuando la empresa no existe o aun no se ha calculado; el panel
 * decide como degrada. Solo lectura: nunca dispara recalculos.
 */
export async function getMoatQualityScore(ticker: string): Promise<MoatScoreMetric | null> {
  const normalizedTicker = ticker.trim().toUpperCase();
  try {
    const data = await researchRequest<CalculatedMetricsResponse>(
      `/api/companies/${encodeURIComponent(normalizedTicker)}/metrics/calculated`,
      { fast: true, cache: 'no-store' },
    );
    return data.metrics.find((metric) => metric.metric === 'quality_moat_score_v2') ?? null;
  } catch (error) {
    if (error instanceof AppError && error.statusCode === 404) return null;
    throw error;
  }
}

export async function getResearchThesisWorkspace(ticker: string) {
  const encoded = encodeURIComponent(ticker.toUpperCase());
  const optional = async <T>(path: string, fallback: T): Promise<{ value: T; error?: string }> => {
    try {
      return { value: await getJson<T>(path, fallback) };
    } catch (error) {
      // Una capa secundaria no puede convertir el resto del workspace en 500.
      return { value: fallback, error: getSafeErrorMessage(error) };
    }
  };
  const [thesis, history, claims, sections, graph, redTeam, historyDetail] = await Promise.all([
    getJson<ResearchThesis | null>(`/api/thesis/${encoded}/latest`, null),
    optional<ResearchThesisVersion[]>(`/api/thesis/${encoded}/versions`, []),
    optional<ResearchClaim[]>(`/api/memory/claims?ticker=${encoded}&limit=100`, []),
    optional<ResearchThesisSection[]>(`/api/memory/thesis/${encoded}/sections`, []),
    optional<ResearchThesisGraph | null>(`/api/thesis/${encoded}/graph`, null),
    optional<ResearchRedTeam | null>(`/api/companies/${encoded}/red-team/latest`, null),
    optional<{ count: number; history: ResearchThesisHistoryEntry[] }>(
      `/api/thesis/${encoded}/history`,
      { count: 0, history: [] },
    ),
  ]);
  const errors = [history, claims, sections, graph, redTeam, historyDetail]
    .map((result) => result.error)
    .filter((error): error is string => Boolean(error));
  return {
    thesis: thesis ?? null,
    history: history.value,
    claims: claims.value,
    sections: sections.value,
    graph: graph.value,
    redTeam: redTeam.value,
    historyDetail: historyDetail.value,
    partial: errors.length > 0,
    errors,
  };
}

export async function getResearchChangesWorkspace(ticker: string) {
  const encoded = encodeURIComponent(ticker.toUpperCase());
  const [changes, reviews, alerts, decisions, expectations, trades] = await Promise.all([
    getJson<ResearchThesisChange[]>(`/api/memory/thesis/${encoded}/changes?limit=100`, []),
    getJson<ResearchReview[]>(`/api/reviews?ticker=${encoded}`, []),
    getJson<ResearchAlert[]>(`/api/alerts?ticker=${encoded}&include_snoozed=true`, []),
    getJson<ResearchDecisionJournalEntry[]>(`/api/companies/${encoded}/decision-journal`, []),
    getJson<ResearchExpectationReview[]>(`/api/companies/${encoded}/expectation-reality`, []),
    // Compras/ventas del ticker para enlazarlas al diario; [] si no hay o falla.
    getJson<JournalTrade[]>(`/api/companies/${encoded}/decision-journal/trades`, []),
  ]);
  return { changes, reviews, alerts, decisions, expectations, trades };
}

export async function getResearchFinancialsWorkspace(ticker: string) {
  const encoded = encodeURIComponent(ticker.toUpperCase());
  const [facts, metrics, ttm] = await Promise.all([
    getJson<ResearchFact[]>(`/api/companies/${encoded}/facts?limit=250`, []),
    getJson<{ metrics: ResearchCalculatedMetric[] }>(
      `/api/companies/${encoded}/metrics/calculated`,
      { metrics: [] },
    ),
    // Fundamentales actuales en TTM (últimos 4 trimestres) con respaldo FY.
    getJson<ResearchTtm | null>(`/api/companies/${encoded}/ttm`, null),
  ]);
  return { facts, calculatedMetrics: metrics.metrics, ttm };
}

export async function getResearchLongTermModel(ticker: string) {
  return getJson<ResearchLongTermModel | null>(
    `/api/companies/${encodeURIComponent(ticker.toUpperCase())}/long-term-model`,
    null,
  );
}

export async function getResearchMoatWorkspace(ticker: string) {
  return getJson<ResearchMoat | null>(
    `/api/companies/${encodeURIComponent(ticker.toUpperCase())}/moat`,
    null,
  );
}

export async function getResearchPeersWorkspace(ticker: string) {
  const encoded = encodeURIComponent(ticker.toUpperCase());
  const [comparison, analysis] = await Promise.all([
    getJson<ResearchPeerComparison | null>(`/api/companies/${encoded}/peers/comparison`, null),
    getJson<ResearchPeerAnalysis | null>(`/api/companies/${encoded}/peers/analysis`, null),
  ]);
  return { comparison, analysis };
}

export async function getResearchValuationWorkspace(ticker: string) {
  return getJson<ResearchValuation | null>(
    `/api/valuation/${encodeURIComponent(ticker.toUpperCase())}`,
    null,
  );
}

export async function getResearchDocumentsWorkspace(
  ticker: string,
  includeChunks = false,
) {
  const encoded = encodeURIComponent(ticker.toUpperCase());
  // La ficha de una empresa debe listar SUS documentos aunque no este en
  // cartera/watchlist: el default `followed` es solo para el inventario global.
  return getJson<ResearchSourceDocument[]>(
    `/api/sources/documents?ticker=${encoded}&scope=all&include_chunks=${includeChunks ? 'true' : 'false'}`,
    [],
  );
}

export async function getResearchSourceAuditsWorkspace(ticker?: string) {
  const query = ticker ? `?ticker=${encodeURIComponent(ticker.toUpperCase())}` : '';
  return getJson<ResearchSourceAudit[]>(`/api/sources/audits${query}`, []);
}

export async function createResearchDecision(ticker: string, formData: FormData) {
  const normalizedTicker = ticker.toUpperCase();
  const decision = String(formData.get('decision') ?? '').trim();
  const rationale = String(formData.get('rationale') ?? '').trim();
  const whatMustBeTrue = String(formData.get('what_must_be_true') ?? '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!['buy', 'hold', 'trim', 'sell', 'watch', 'avoid'].includes(decision)) {
    throw new ValidationError('Selecciona una decisión válida', 'decision');
  }
  if (rationale.length < 5) {
    throw new ValidationError('Explica la decisión con al menos 5 caracteres', 'rationale');
  }
  const rawTransaction = String(formData.get('transaction_id') ?? '').trim();
  const transactionId = /^\d+$/.test(rawTransaction) ? Number(rawTransaction) : null;
  await postJson(
    `/api/companies/${encodeURIComponent(normalizedTicker)}/decision-journal`,
    null,
    {
      decision,
      rationale,
      what_must_be_true: whatMustBeTrue,
      ...(transactionId ? { transaction_id: transactionId } : {}),
    },
  );
  revalidatePath(`/research/${normalizedTicker}`);
}

/** PUT /api/companies/{ticker}/decision-journal/{id}/transaction: enlaza una
 *  entrada existente a una compra/venta (o la desenlaza con valor vacío). */
export async function linkResearchDecisionTrade(ticker: string, entryId: number, formData: FormData) {
  await requireAuthenticatedUser();
  const normalizedTicker = ticker.toUpperCase();
  const raw = String(formData.get('transaction_id') ?? '').trim();
  if (raw !== '' && !/^\d+$/.test(raw)) throw new ValidationError('Operación no válida', 'transaction_id');
  if (!Number.isInteger(entryId) || entryId <= 0) throw new ValidationError('Entrada no válida', 'entry_id');
  await researchRequest(
    `/api/companies/${encodeURIComponent(normalizedTicker)}/decision-journal/${entryId}/transaction`,
    { method: 'PUT', body: JSON.stringify({ transaction_id: raw === '' ? null : Number(raw) }) },
  );
  revalidatePath(`/research/${normalizedTicker}`);
}

export async function reviewResearchExpectations(ticker: string) {
  const normalizedTicker = ticker.toUpperCase();
  await postJson(
    `/api/companies/${encodeURIComponent(normalizedTicker)}/expectation-reality/review`,
    [],
  );
  revalidatePath(`/research/${normalizedTicker}`);
}

export async function refreshCompanyFinancials(ticker: string) {
  const normalizedTicker = ticker.toUpperCase();
  await postJson(`/api/companies/${encodeURIComponent(normalizedTicker)}/refresh/fmp`, {
    status: 'not_configured',
    ticker: normalizedTicker,
  });
  revalidatePath('/research');
  revalidatePath(`/research/${normalizedTicker}`);
}

export async function refreshCompanyResearchModel(ticker: string) {
  const normalizedTicker = ticker.toUpperCase();
  await postJson(
    `/api/companies/${encodeURIComponent(normalizedTicker)}/snapshot/refresh?horizon=5`,
    null,
  );
  revalidatePath(`/research/${normalizedTicker}`);
}
/** Resultado como valor: un Server Action en producción oculta el mensaje de
 *  las excepciones, y el 422 del backend explica qué criterio no es válido. */
export type SaveInvalidationRulesResult = { ok: true; count: number } | { ok: false; error: string };

/** PUT /api/thesis/{ticker}/invalidation-rules: guarda los criterios medibles
 *  en la última versión de la tesis; el evaluador de alertas los vigila. */
export async function saveThesisInvalidationRules(
  ticker: string,
  rules: Array<{ metric: string; operator: string; threshold: number; description?: string | null }>,
): Promise<SaveInvalidationRulesResult> {
  await requireAuthenticatedUser();
  const normalizedTicker = ticker.toUpperCase();
  try {
    const result = await researchRequest<{ invalidation_rules: unknown[] }>(
      `/api/thesis/${encodeURIComponent(normalizedTicker)}/invalidation-rules`,
      { method: 'PUT', body: JSON.stringify({ rules }) },
    );
    revalidatePath(`/research/${normalizedTicker}`);
    return { ok: true, count: Array.isArray(result?.invalidation_rules) ? result.invalidation_rules.length : 0 };
  } catch (error) {
    return { ok: false, error: getSafeErrorMessage(error) || 'No se pudieron guardar los criterios.' };
  }
}

export async function createResearchClaim(ticker: string, formData: FormData) {
  const normalizedTicker = ticker.toUpperCase();
  const statement = String(formData.get('statement') ?? '').trim();
  const claimType = String(formData.get('claim_type') ?? 'thesis').trim() || 'thesis';
  const materiality = Number(formData.get('materiality_score') ?? 5);

  if (statement.length < 5) throw new ValidationError('La afirmación debe tener al menos 5 caracteres', 'statement');

  await postJson('/api/memory/claims', null, {
    ticker: normalizedTicker,
    statement,
    claim_type: claimType,
    materiality_score: Number.isFinite(materiality) ? Math.max(0, Math.min(10, materiality)) : 5,
    created_by: 'user',
  });

  revalidatePath('/research');
  revalidatePath(`/research/${normalizedTicker}`);
}
export async function askResearchCompanyChat(
  ticker: string,
  question: string,
  enableDebate = false,
): Promise<ResearchChatResponse | null> {
  const normalizedTicker = ticker.toUpperCase();
  const trimmedQuestion = question.trim();
  if (trimmedQuestion.length < 3) return null;

  return postJson<ResearchChatResponse>(
    '/api/chat',
    {
      answer: 'El motor de research no está disponible ahora. Reinténtalo en unos segundos.',
      sections: [],
      sources: [],
      blocked: true,
      proposed_actions: ['Comprueba el estado del backend'],
      evidence_suggestions: [],
    },
    {
      ticker: normalizedTicker,
      scope: 'company',
      question: trimmedQuestion,
      enable_debate: enableDebate,
      page: { path: `/research/${normalizedTicker}`, label: normalizedTicker, ticker: normalizedTicker },
    },
  );
}

export type ResearchSourcesScope = 'followed' | 'all';

export type ResearchSourcesOptions = {
  ticker?: string;
  page?: number;
  /** `followed` (default del backend) = cartera + watchlist del tenant. */
  scope?: ResearchSourcesScope;
  /** Valor exacto del catalogo de tipos (`sec`, `manual_upload`, ...). */
  sourceType?: string;
  /** Busqueda ILIKE en el titulo; el backend la acota a 120 caracteres. */
  q?: string;
};

export async function getResearchSources(options: ResearchSourcesOptions = {}) {
  // La lista de documentos pagina (50): el total real viene de /count para
  // no presentar el tamano de pagina como si fuera el inventario (F131).
  // Si /count no responde (backend antiguo), el total es DESCONOCIDO (null):
  // mostrar 0 con la tabla poblada seria falso (F154).
  // Los filtros (ticker, alcance, tipo, busqueda) se pasan a AMBOS endpoints:
  // el total y la pagina deben hablar del mismo subconjunto. La pagina se
  // acota con el total: una fuera de rango cae en la ultima, nunca en vacia.
  const filters = new URLSearchParams();
  const ticker = options.ticker?.trim().toUpperCase();
  if (ticker) filters.set('ticker', ticker);
  if (options.scope) filters.set('scope', options.scope);
  const sourceType = options.sourceType?.trim();
  if (sourceType) filters.set('source_type', sourceType);
  const q = options.q?.trim().slice(0, 120);
  if (q) filters.set('q', q);
  const countQuery = filters.size ? `?${filters.toString()}` : '';
  const documentsCount = await getJson<{ total: number } | null>(`/api/sources/documents/count${countQuery}`, null);
  const documentsTotal = documentsCount?.total ?? null;
  const requested = options.page && options.page > 0 ? Math.floor(options.page) : 1;
  // Sin total no hay forma honesta de acotar: se pide la pagina tal cual.
  const pageInfo = documentsTotal === null ? null : sourcesPageInfo(documentsTotal, requested);
  const effectivePage = pageInfo?.page ?? requested;
  const params = new URLSearchParams(filters);
  if (effectivePage > 1) params.set('page', String(effectivePage));
  const documentsQuery = params.size ? `?${params.toString()}` : '';
  const [documents, audits] = await Promise.all([
    getJson<ResearchSourceDocument[]>(`/api/sources/documents${documentsQuery}`, []),
    getJson<ResearchSourceAudit[]>('/api/sources/audits', []),
  ]);

  return {
    documents,
    audits,
    documentsTotal,
    pageInfo,
  };
}

export async function importResearchSource(formData: FormData) {
  const ticker = String(formData.get('ticker') ?? '').trim().toUpperCase();
  const title = String(formData.get('title') ?? '').trim();
  const text = String(formData.get('text') ?? '').trim();
  const sourceUrl = String(formData.get('source_url') ?? '').trim();
  const period = String(formData.get('period') ?? '').trim() || 'unknown';

  if (!ticker) throw new ValidationError('El ticker es obligatorio', 'ticker');
  if (!title) throw new ValidationError('El título es obligatorio', 'title');
  if (text.length < 20) throw new ValidationError('El documento debe tener al menos 20 caracteres', 'text');

  const sourceType = String(formData.get('source_type') ?? 'manual_upload');
  if (!['manual_upload', 'manual_transcript', 'company_ir'].includes(sourceType)) {
    throw new ValidationError('Selecciona un tipo de fuente válido', 'source_type');
  }
  if (sourceType === 'manual_transcript') {
    await postJson('/api/sources/transcripts/import-text', null, {
      ticker, title, text, source_url: sourceUrl || null, period,
    });
  } else {
    const payload = new FormData();
    payload.set('ticker', ticker);
    payload.set('title', title);
    payload.set('source_type', sourceType);
    if (sourceUrl) payload.set('source_url', sourceUrl);
    payload.set('file', new File([text], 'manual-source.txt', { type: 'text/plain' }));
    await postForm('/api/sources/documents/ingest-file', null, payload);
  }

  revalidatePath('/research/sources');
}

export async function importResearchDocumentFile(formData: FormData) {
  const ticker = String(formData.get('ticker') ?? '').trim().toUpperCase();
  const title = String(formData.get('title') ?? '').trim();
  const file = formData.get('file');

  if (!ticker) throw new ValidationError('El ticker es obligatorio', 'ticker');
  if (!title) throw new ValidationError('El título es obligatorio', 'title');
  if (!(file instanceof File) || file.size === 0) throw new ValidationError('Selecciona un archivo no vacío', 'file');

  const result = await postForm<{ document_id: number; ticker: string; status: string } | null>('/api/sources/documents/ingest-file', null, formData);
  revalidatePath('/research/sources');
  revalidatePath(`/research/${ticker}`);
  if (!result) throw new ExternalAPIError('No se pudo confirmar el documento importado', 'research-api');
  return { message: `${result.status === 'duplicate' ? 'Documento ya existente' : 'Documento importado'}: ${result.ticker} · #${result.document_id}.` };
}

export async function importResearchDocumentUrl(formData: FormData) {
  const ticker = String(formData.get('ticker') ?? '').trim().toUpperCase();
  const title = String(formData.get('title') ?? '').trim();
  const url = String(formData.get('url') ?? '').trim();
  const sourceType = String(formData.get('source_type') ?? 'url').trim() || 'url';

  if (!ticker) throw new ValidationError('El ticker es obligatorio', 'ticker');
  if (!title) throw new ValidationError('El título es obligatorio', 'title');
  if (!url) throw new ValidationError('La URL es obligatoria', 'url');

  await postJson('/api/sources/documents/ingest-url', null, {
    ticker,
    title,
    url,
    source_type: sourceType,
  });
  revalidatePath('/research/sources');
  revalidatePath(`/research/${ticker}`);
}

export type ResearchNewsEvent = {
  /** Tickers relacionados (evidencia explícita en el texto) con último cierre y variación; null si no hay. */
  related_tickers?: import('@/lib/news-related-tickers').RelatedTicker[] | null;
  original_headline?: string;
  /** Misma historia en otros medios, agrupada en portada (PR story clusters). */
  coverage_count?: number | null;
  coverage?: {source: string; url: string | null; title?: string}[] | null;
  headline_translation?: {text: string; target_language: string; machine_translation: boolean} | null;
  /** Resumen/cuerpo ingerido y su traducción cacheada (misma procedencia que el titular). */
  summary?: string;
  summary_translation?: {text: string; target_language: string; machine_translation: boolean} | null;
  id: number;
  ticker: string | null;
  date: string;
  title: string;
  source: string;
  url: string | null;
  event_type: string;
  materiality_score: number;
  impact_direction: string;
  requires_update: boolean;
  /** 'source' = fecha de la fuente; 'ingested_at_fallback' = la fuente no da fecha. */
  date_source?: string | null;
  /** 'macro' = evento macro sin ticker; 'gobierno' = fuente oficial; null/ausente = empresa. */
  news_lane?: string | null;
  /** true = el carril macro no tiene frescura (fuente caída) y la API sirve
   *  el archivo reciente marcado: la UI lo anuncia y nunca finge frescura. */
  archive?: boolean;
  /** false = título de display generado por GerarAI (la UI omite el prefijo de ticker). */
  headline_from_source?: boolean;
  macro_theme?: string | null;
  source_tier?: string;
  source_trust_score?: number;
  portfolio_weight?: number;
  materiality_reasons?: string[];
  source_policy?: string;
  model_route?: string;
};

type ResearchWorkflowRun = {
  status: string;
  workflow: string;
  ticker: string | null;
  message: string;
  steps: string[];
  estimated_minutes: number;
  result?: unknown;
};

type ResearchThesisVersion = {
  id: number;
  version: number;
  status: string;
  rating: string;
  executive_summary: string;
  source_coverage_score: number;
  data_confidence_score: number;
  created_at: string;
};

export async function getResearchNews(
  lane: 'empresa' | 'macro' | 'gobierno' | 'para-ti' | null = null,
  offset = 0,
  limit = 30,
  ticker: string | null = null,
  /** Carril «Para ti»: tickers de cartera + watchlist del usuario (los conoce el cliente). */
  tickers: string[] = [],
): Promise<ResearchNewsEvent[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (lane === 'empresa' || lane === 'macro' || lane === 'gobierno') params.set('lane', lane);
  if (ticker) params.set('ticker', ticker);
  if (lane === 'para-ti' && tickers.length) params.set('tickers', tickers.join(','));
  const events = await getJson<ResearchNewsEvent[]>(`/api/news?${params.toString()}`, []);
  // Barrera de presentación: la ingesta a veces indexa la página de
  // cotización de Yahoo como si fuera una noticia (caso HYMC 21-oct-2026).
  // Una landing no es una noticia en NINGUNA superficie (ficha, «Ver
  // todas», carriles); la clasificación durable es del backend.
  return events.filter((event) => !isQuoteLandingEvent(event));
}

export async function analyzeManualNews(
  formData: FormData,
): Promise<{
  ticker?: string | null;
  event_type: string;
  materiality_score: number;
  impact_direction: string;
  summary: string;
  source_tier?: string;
  portfolio_weight?: number;
  materiality_reasons?: string[];
}> {
  const text = String(formData.get('text') ?? '').trim();
  const source = String(formData.get('source') ?? 'manual').trim();
  const url = String(formData.get('url') ?? '').trim();
  if (!text || text.length < 20) throw new ValidationError('La noticia debe tener al menos 20 caracteres', 'text');

  const result = await postJson(
    '/api/news/manual',
    { ticker: null, event_type: 'unknown', materiality_score: 0, impact_direction: 'neutral', summary: '' },
    { text, source, url: url || null },
  );

  revalidatePath('/research');
  revalidatePath('/research/news');
  if (result.ticker) revalidatePath(`/research/${result.ticker}`);

  return result;
}

export async function ingestResearchNewsFeed(
  formData: FormData,
): Promise<{ status: string; received: number; created: number; skipped_duplicates: number; requires_update: number }> {
  const rawItems = String(formData.get('items') ?? '').trim();
  const source = String(formData.get('source') ?? 'manual_feed').trim() || 'manual_feed';
  if (!rawItems) throw new ValidationError('Introduce al menos una noticia en JSON', 'items');

  try {
    const parsed = JSON.parse(rawItems) as unknown;
    const items = Array.isArray(parsed) ? parsed : [parsed];
    const result = await postJson(
      '/api/news/ingest',
      { status: 'error', received: 0, created: 0, skipped_duplicates: 0, requires_update: 0 },
      { source, items },
    );

    revalidatePath('/research');
    revalidatePath('/research/news');
    return result;
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw new ValidationError('El feed no contiene JSON válido', 'items');
  }
}

export async function refreshCompanyFinancialsSEC(ticker: string) {
  const normalizedTicker = ticker.toUpperCase();
  await postJson(`/api/companies/${encodeURIComponent(normalizedTicker)}/refresh/sec`, {
    status: 'not_configured',
    ticker: normalizedTicker,
  });
  revalidatePath('/research');
  revalidatePath(`/research/${normalizedTicker}`);
}

export async function refreshCompanyFinancialsESEF(ticker: string) {
  const normalizedTicker = ticker.toUpperCase();
  await postJson(`/api/companies/${encodeURIComponent(normalizedTicker)}/refresh/esef`, {
    status: 'not_configured',
    ticker: normalizedTicker,
  });
  revalidatePath('/research');
  revalidatePath(`/research/${normalizedTicker}`);
}

export async function runResearchWorkflow(name: string, ticker?: string): Promise<ResearchWorkflowRun> {
  const result = await postJson<ResearchWorkflowRun>(
    `/api/workflows/${encodeURIComponent(name)}/run`,
    { status: 'error', workflow: name, ticker: ticker ?? null, message: 'Backend unavailable', steps: [], estimated_minutes: 0 },
    { ticker: ticker ?? null, params: {} },
  );
  revalidatePath('/research');
  if (ticker) revalidatePath(`/research/${ticker.toUpperCase()}`);
  return result;
}

export async function submitThesisHumanInput(ticker: string, formData: FormData) {
  const normalizedTicker = ticker.toUpperCase().trim();
  const driverKey = String(formData.get('driver_key') ?? '').trim();
  const source = String(formData.get('source') ?? '').trim();
  const rationale = String(formData.get('rationale') ?? '').trim();
  const scenario = String(formData.get('scenario') ?? 'base');
  const rawYear = String(formData.get('fiscal_year') ?? '').trim();
  const rawValue = String(formData.get('value') ?? '').trim();
  const year = Number(rawYear);
  if (!driverKey || driverKey.length > 160 || !source || source.length > 240 || !rationale || rationale.length > 5000) {
    throw new ValidationError('Indica el driver, la fuente y la justificación.', 'inputs');
  }
  if (!['bear', 'base', 'bull'].includes(scenario) || !rawYear || !Number.isInteger(year) || year < 1900 || year > 2200) {
    throw new ValidationError('Indica un escenario y ejercicio fiscal válidos.', 'inputs');
  }
  if (!rawValue || !Number.isFinite(Number(rawValue))) {
    throw new ValidationError('Indica un valor numérico finito en la unidad del driver.', 'value');
  }
  await researchRequest(`/api/thesis/${encodeURIComponent(normalizedTicker)}/inputs`, {
    method: 'POST',
    body: JSON.stringify({ inputs: [{ driver_key: driverKey, fiscal_year: year, scenario, value: rawValue, source, rationale }] }),
  });
  // Saving a human assumption never silently triggers thesis generation.
  revalidatePath(`/research/${normalizedTicker}`);
}


/** Index relevance needs membership, not prices, FX totals or data quality. */
export async function getResearchPortfolioPositions(): Promise<Array<{ ticker: string; quantity: number }>> {
  await requireAuthenticatedUser();
  // El backend pagina con page/page_size (max 200): limit/offset NO existen
  // en este endpoint y los ignoraba, repitiendo siempre la pagina 1.
  return fetchAllBackendPages((page) =>
    researchRequest<PaginatedBackendResponse<{ ticker: string; quantity: number }>>(
      `/api/portfolio/positions?page=${page}&page_size=${BACKEND_PAGE_SIZE}`, { fast: true },
    ),
    (position) => position.ticker,
  );
}

/** Read only: opening a company never starts a 13D/G scan. */
export async function getParticipationFilings(ticker: string): Promise<import('@/lib/research/schedule13dg').ParticipationResponse> {
  await requireAuthenticatedUser();
  return getJson<import('@/lib/research/schedule13dg').ParticipationResponse>(`/api/ownership/schedule-13dg?ticker=${encodeURIComponent(ticker.trim().toUpperCase())}`, { ticker, count: 0, filings: [] });
}
