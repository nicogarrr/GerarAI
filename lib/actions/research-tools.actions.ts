'use server';

import { revalidatePath } from 'next/cache';

import { normalizeResearchBody, researchIdentityHeaders } from '@/lib/auth/research-identity';
import { RESEARCH_TIMEOUTS, requestSignal } from '@/lib/research/client';
import { AppError, ExternalAPIError, ValidationError } from '@/lib/types/errors';
import { assertPositiveInt } from '@/lib/validation/pathParams';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

export type KnowledgeCollection = {
  id: number;
  name: string;
  slug: string;
  description: string;
  collection_type: string;
  metadata: Record<string, unknown>;
};

export type KnowledgeDocument = {
  id: number;
  collection_id: number | null;
  title: string;
  author: string | null;
  document_type: string;
  source_url: string | null;
  publication_date: string | null;
  language: string;
  status: string;
  checksum: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type InvestmentPrinciple = {
  id: number;
  knowledge_document_id: number;
  knowledge_chunk_id: number;
  collection_id: number | null;
  principle: string;
  principle_fingerprint: string;
  semantic_duplicate_of_id: number | null;
  canonical_principle_id: number | null;
  version: number;
  superseded_by_id: number | null;
  category: string;
  application_conditions: string[];
  exceptions: string[];
  applies_to_company_ids: number[];
  exact_fragment: string;
  page_number: number | null;
  author: string | null;
  confidence: string | number;
  status: string;
  approved_by: string | null;
  approved_at: string | null;
  metadata: Record<string, unknown>;
};

export type KnowledgeProcessingJob = {
  id: number;
  job_type: string;
  entity_type: string;
  entity_id: number | null;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed';
  progress_current: number;
  progress_total: number;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeChunk = {
  id: number;
  knowledge_document_id: number;
  chunk_index: number;
  content: string;
  page_number: number | null;
  section_title: string | null;
  token_count: number;
  source_locator: Record<string, unknown>;
};

export type UniversalSearchResult = {
  entity_type: string;
  entity_id: number;
  title: string;
  text: string;
  ticker: string | null;
  collection: string | null;
  status: string;
  source_type: string;
  source_tier: string;
  source_trust: number;
  as_of: string | null;
  citation: string;
  scores: { lexical: number; vector: number; rrf: number; reranker: number };
};

export type UniversalSearchResponse = {
  query: string;
  status?: string;
  filters?: Record<string, unknown>;
  retrieval: Record<string, unknown>;
  total: number;
  results: UniversalSearchResult[];
};

export type CustomMetric = {
  id: number;
  metric_key: string;
  name: string;
  formula: string;
  unit: string;
  description: string;
  version: number;
  active: boolean;
  created_at: string;
};

export type ScreenCriterion = {
  left: string;
  operator: '>' | '>=' | '<' | '<=' | '==' | '!=';
  right: string;
};

export type SavedScreen = {
  id: number;
  name: string;
  description: string;
  criteria: ScreenCriterion[];
  ranking_formula: string | null;
  ranking_direction: 'asc' | 'desc';
  alerts_enabled: boolean;
  active: boolean;
  last_run_at: string | null;
  created_at: string;
};

export type ScreenResult = {
  criteria: ScreenCriterion[];
  ranking_formula: string | null;
  ranking_direction: string;
  company_count: number;
  match_count: number;
  metrics_without_data?: string[];
  new_match_company_ids?: number[];
  results: Array<{
    company_id: number;
    ticker: string;
    name: string;
    matched: boolean;
    rank_value: string | null;
    coverage_percent: number;
    confidence: string;
    latest_data_at: string | null;
    missing_fields: string[];
    criteria: Array<ScreenCriterion & {
      left_value?: string;
      right_value?: string;
      passed: boolean;
      missing_fields?: string[];
    }>;
  }>;
};

export type FinancialTerminal = {
  ticker: string;
  company: string;
  periodicity: string;
  years: number;
  range: { from_fiscal_year: number; to_fiscal_year: number };
  coverage: { requested: number; available: number; percent: number; missing: string[] };
  metrics: Array<{
    metric: string;
    definition: string;
    canonical_formula: string | null;
    definition_version: string | null;
    status: string;
    periods: number;
    segments: string[];
    series: Array<{
      id: number | null;
      period: string;
      fiscal_year: number | null;
      fiscal_quarter: string | null;
      frequency: string;
      segment: string;
      value: string | number | null;
      unit: string;
      confidence: string | number;
      status: string;
      formula: string | null;
      source: { type: string; document_id?: number | null; title?: string | null; url?: string | null; source_fact_ids?: number[] };
    }>;
  }>;
};

export type DriverAssumption = {
  id: number;
  driver_id: number;
  driver_key: string;
  fiscal_year: number;
  scenario: 'bear' | 'base' | 'bull';
  value: string | number;
  source: string;
  user_override: boolean;
  confidence: string | number;
  rationale: string;
  previous_version_id: number | null;
  created_at: string;
};

export type DecisionLesson = {
  id: number;
  decision_journal_entry_id: number | null;
  expectation_review_id: number | null;
  taxonomy: string;
  expectation: string;
  outcome: string;
  deviation: string;
  cause: string;
  error: string;
  lesson: string;
  future_application: string;
  evidence: Array<Record<string, unknown>>;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ManagementCredibility = {
  ticker: string;
  score: number | null;
  grade: string;
  counts: { total: number; open: number; met: number; partial: number; missed: number };
  method: string;
  promises: Array<{
    id: number;
    promise: string;
    promise_date: string;
    expected_period: string;
    metric: string | null;
    operator: string | null;
    target_value: string | number | null;
    unit: string | null;
    actual_value: string | number | null;
    status: string;
    management_explanation: string | null;
    verified_at: string | null;
    evidence: Array<Record<string, unknown>>;
  }>;
};

export type PortfolioIntelligence = {
  as_of: string;
  base_currency: string;
  horizon_years: number;
  performance: { twr: number | null; xirr: number | null; annualized_return: number | null; trace: Record<string, unknown>; twr_method: string; twr_is_exact: boolean };
  risk: {
    max_drawdown: number | null;
    drawdown_series: Array<{ date: string; drawdown: number }>;
    volatility: number | null;
    sharpe: number | null;
    sortino: number | null;
    var_95: number | null;
    cvar_95: number | null;
    calmar: number | null;
    beta: number | null;
    beta_trace: Record<string, unknown>;
    correlations: Record<string, Record<string, number | null>>;
  };
  concentration: { top_1: number; top_5: number; herfindahl: number; weights: Record<string, number> };
  exposures: Record<'sectors' | 'countries' | 'currencies' | 'factors', Record<string, number>>;
  attribution: {
    basis?: 'adjusted_price_return';
    period_start?: string | null;
    period_end?: string | null;
    portfolio_components: Record<string, number | null>;
    incomplete_components?: string[];
    positions: Array<{ ticker: string; weight: number; total_return: number | null; period_start?: string | null; period_end?: string | null; components: Record<string, number | null> }>;
  };
  ledger_contribution: {
    positions: Array<{
      ticker: string;
      contribution_pnl: number | null;
      contribution_share: number | null;
      end_value: number;
      start_value: number;
      net_invested: number;
      income: number;
      reason: string | null;
    }>;
    total_pnl: number | null;
    coverage: { positions: number; with_contribution: number; reasons: Record<string, number> };
    methodology: string;
    base_currency: string;
  };
  benchmark: {
    symbol: string;
    status: 'calculated' | 'missing_benchmark' | 'insufficient_overlap';
    benchmark_twr: number | null;
    benchmark_annualized: number | null;
    portfolio_annualized: number | null;
    alpha_annualized: number | null;
    tracking_error: number | null;
    information_ratio: number | null;
    observations: number;
  };
  coverage: { positions: number; positions_with_price_history: number; price_history_percent: number; portfolio_snapshots: number; snapshot_returns: number; snapshot_pricing_complete: number; limitations: string[] };
};

export type KnowledgeGraph = {
  node_count: number;
  edge_count: number;
  /** Total con los MISMOS filtros, sin el `limit` del backend. Ausente en el
   *  vecindario de un nodo (ahi no hay paginacion): null/ausente = N/D. */
  total_node_count?: number;
  nodes: Array<{ id: number; key: string; type: string; label: string; description: string; company_id: number | null; entity_type: string | null; entity_id: number | null; confidence: string | number; attributes: Record<string, unknown> }>;
  edges: Array<{ id: number; from: number; to: number; type: string; weight: string | number; confidence: string | number; evidence: Array<Record<string, unknown>>; provenance: string }>;
};

async function apiError(response: Response, path: string): Promise<never> {
  let detail = `${response.status} ${response.statusText}`.trim();
  try {
    const payload = (await response.json()) as { detail?: string; message?: string };
    detail = payload.detail ?? payload.message ?? detail;
  } catch {
    // Preserve the HTTP status when the service does not return JSON.
  }
  throw new AppError(detail, 'RESEARCH_API_ERROR', response.status, { path });
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const normalized = await normalizeResearchBody(init?.body ?? null);
    const identity = await researchIdentityHeaders({
      method: init?.method ?? 'GET',
      path,
      body: normalized.body ?? null,
    });
    const response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      body: normalized.body ?? undefined,
      cache: 'no-store',
      // Sin timeout una lectura lenta del engine dejaba la página colgada en
      // silencio; respeta la señal del caller si la hay (mismo patrón que
      // lib/research/client.ts).
      signal: requestSignal(init?.signal, RESEARCH_TIMEOUTS.GLOBAL_MS),
      headers: {
        ...identity,
        ...(normalized.contentType
          ? { 'Content-Type': normalized.contentType }
          : normalized.body != null
            ? { 'Content-Type': 'application/json' }
            : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) return apiError(response, path);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw new ExternalAPIError(`Research API request failed: ${path}`, 'research-api', error);
  }
}

function csv(value: string | undefined): string[] {
  return (value ?? '').split(',').map((item) => item.trim()).filter(Boolean);
}

function required(formData: FormData, key: string, label: string): string {
  const value = String(formData.get(key) ?? '').trim();
  if (!value) throw new ValidationError(`${label} is required`, key);
  return value;
}

export async function getKnowledgeLibrary() {
  const [collections, documents, principles, jobs] = await Promise.all([
    requestJson<KnowledgeCollection[]>('/api/knowledge/collections'),
    requestJson<KnowledgeDocument[]>('/api/knowledge/documents'),
    requestJson<InvestmentPrinciple[]>('/api/knowledge/principles?limit=300'),
    requestJson<KnowledgeProcessingJob[]>('/api/knowledge/jobs?limit=100'),
  ]);
  return { collections, documents, principles, jobs };
}

export async function getKnowledgeDocuments() {
  return requestJson<KnowledgeDocument[]>('/api/knowledge/documents?limit=500');
}

export type KnowledgeDocumentDetail = KnowledgeDocument & { chunk_count: number };

/** Un documento por id. `null` si no existe (404); cualquier otro error se propaga. */
export async function getKnowledgeDocument(documentId: number): Promise<KnowledgeDocumentDetail | null> {
  try {
    return await requestJson<KnowledgeDocumentDetail>(`/api/knowledge/documents/${assertPositiveInt(documentId, 'documentId')}`);
  } catch (error) {
    if (error instanceof AppError && error.code === 'RESEARCH_API_ERROR' && error.statusCode === 404) return null;
    throw error;
  }
}

/** Una pagina de fragmentos (orden de lectura) sin tope silencioso: el total viene de `chunk_count`. */
export async function getKnowledgeDocumentChunkPage(documentId: number, offset: number, limit: number) {
  const id = assertPositiveInt(documentId, 'documentId');
  return requestJson<KnowledgeChunk[]>(`/api/knowledge/documents/${id}/chunks?limit=${Math.min(Math.max(1, limit), 100)}&offset=${Math.max(0, offset)}`);
}

export async function getKnowledgeDocumentChunks(documentId: number | null) {
  if (!documentId) return [];
  return requestJson<KnowledgeChunk[]>(`/api/knowledge/documents/${assertPositiveInt(documentId, 'documentId')}/chunks?limit=300`);
}

export async function installKnowledgeDefaults() {
  await requestJson('/api/knowledge/collections/defaults', { method: 'POST' });
  revalidatePath('/knowledge');
}

export async function createKnowledgeCollection(formData: FormData) {
  await requestJson('/api/knowledge/collections', {
    method: 'POST',
    body: JSON.stringify({
      name: required(formData, 'name', 'Name'),
      description: String(formData.get('description') ?? '').trim(),
      collection_type: String(formData.get('collection_type') ?? 'custom').trim() || 'custom',
    }),
  });
  revalidatePath('/knowledge');
}

export async function uploadKnowledgeDocument(formData: FormData) {
  const file = formData.get('file');
  if (!(file instanceof File) || file.size === 0) {
    throw new ValidationError('Choose a non-empty document', 'file');
  }
  for (const key of ['collection_id', 'author', 'source_url', 'publication_date']) {
    if (!String(formData.get(key) ?? '').trim()) formData.delete(key);
  }
  await requestJson('/api/knowledge/documents/upload', { method: 'POST', body: formData });
  revalidatePath('/knowledge');
}

export async function extractKnowledgePrinciples(documentId: number) {
  await requestJson(`/api/knowledge/documents/${assertPositiveInt(documentId, 'documentId')}/extract-principles`, { method: 'POST' });
  revalidatePath('/knowledge');
}

export async function decideKnowledgePrinciple(
  principleId: number,
  action: 'approve' | 'reject',
) {
  await requestJson(`/api/knowledge/principles/${assertPositiveInt(principleId, 'principleId')}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, actor: 'user' }),
  });
  revalidatePath('/knowledge');
}

export async function mergeKnowledgePrinciple(principleId: number, canonicalId: number) {
  await requestJson(`/api/knowledge/principles/${assertPositiveInt(principleId, 'principleId')}/action`, {
    method: 'POST',
    body: JSON.stringify({
      action: 'merge',
      actor: 'user',
      canonical_principle_id: canonicalId,
    }),
  });
  revalidatePath('/knowledge');
}

export async function reviseKnowledgePrinciple(principleId: number, formData: FormData) {
  await requestJson(`/api/knowledge/principles/${assertPositiveInt(principleId, 'principleId')}`, {
    method: 'PUT',
    body: JSON.stringify({
      principle: required(formData, 'principle', 'Principle'),
      category: required(formData, 'category', 'Category'),
      application_conditions: csv(String(formData.get('application_conditions') ?? '')),
      exceptions: csv(String(formData.get('exceptions') ?? '')),
      actor: 'user',
    }),
  });
  revalidatePath('/knowledge');
}

export async function searchResearchLibrary(input: {
  query: string;
  ticker?: string;
  entityTypes?: string;
  sourceTypes?: string;
  statuses?: string;
  collectionId?: number;
  dateFrom?: string;
  dateTo?: string;
  includeVector?: boolean;
}): Promise<UniversalSearchResponse> {
  if (!input.query.trim()) return { query: '', total: 0, retrieval: {}, results: [] };
  return requestJson('/api/search', {
    method: 'POST',
    body: JSON.stringify({
      query: input.query.trim(),
      ticker: input.ticker?.trim().toUpperCase() || null,
      entity_types: csv(input.entityTypes),
      source_types: csv(input.sourceTypes),
      statuses: csv(input.statuses),
      collection_id: input.collectionId || null,
      date_from: input.dateFrom || null,
      date_to: input.dateTo || null,
      limit: 50,
      include_vector: input.includeVector !== false,
    }),
  });
}

function criteriaFromForm(formData: FormData): ScreenCriterion[] {
  const criteria: ScreenCriterion[] = [];
  for (const suffix of ['', '_2', '_3']) {
    const left = String(formData.get(`left${suffix}`) ?? '').trim();
    const right = String(formData.get(`right${suffix}`) ?? '').trim();
    if (!left && !right) continue;
    if (!left || !right) throw new ValidationError('Both sides of each criterion are required', `left${suffix}`);
    const operator = String(formData.get(`operator${suffix}`) ?? '>=') as ScreenCriterion['operator'];
    criteria.push({ left, operator, right });
  }
  if (!criteria.length) throw new ValidationError('Add at least one criterion', 'left');
  return criteria;
}

export async function getScreenerWorkspace() {
  const [metrics, screens] = await Promise.all([
    requestJson<CustomMetric[]>('/api/screeners/custom-metrics'),
    requestJson<SavedScreen[]>('/api/screeners/screens'),
  ]);
  return { metrics, screens };
}

export async function createCustomMetric(formData: FormData) {
  await requestJson('/api/screeners/custom-metrics', {
    method: 'POST',
    body: JSON.stringify({
      metric_key: required(formData, 'metric_key', 'Metric key'),
      name: required(formData, 'name', 'Name'),
      formula: required(formData, 'formula', 'Formula'),
      unit: String(formData.get('unit') ?? 'decimal').trim() || 'decimal',
      description: String(formData.get('description') ?? '').trim(),
    }),
  });
  revalidatePath('/screeners');
}

export async function createSavedScreen(formData: FormData) {
  await requestJson('/api/screeners/screens', {
    method: 'POST',
    body: JSON.stringify({
      name: required(formData, 'name', 'Name'),
      description: String(formData.get('description') ?? '').trim(),
      criteria: criteriaFromForm(formData),
      ranking_formula: String(formData.get('ranking_formula') ?? '').trim() || null,
      ranking_direction: String(formData.get('ranking_direction') ?? 'desc'),
      alerts_enabled: formData.get('alerts_enabled') === 'on',
    }),
  });
  revalidatePath('/screeners');
}

export async function runAdHocScreen(input: {
  left: string;
  operator: ScreenCriterion['operator'];
  right: string;
  rankingFormula?: string;
  rankingDirection?: 'asc' | 'desc';
}): Promise<ScreenResult | null> {
  if (!input.left || !input.right) return null;
  return requestJson('/api/screeners/run', {
    method: 'POST',
    body: JSON.stringify({
      criteria: [{ left: input.left, operator: input.operator, right: input.right }],
      ranking_formula: input.rankingFormula || null,
      ranking_direction: input.rankingDirection ?? 'desc',
    }),
  });
}

export async function runSavedScreen(screenId: number): Promise<ScreenResult> {
  return requestJson(`/api/screeners/screens/${assertPositiveInt(screenId, 'screenId')}/run`, { method: 'POST' });
}

export async function getFinancialTerminal(
  ticker: string,
  input: { metrics?: string; years?: number; periodicity?: string } = {},
): Promise<FinancialTerminal> {
  const params = new URLSearchParams({
    years: String(input.years ?? 10),
    periodicity: input.periodicity ?? 'annual',
  });
  if (input.metrics?.trim()) params.set('metrics', input.metrics.trim());
  return requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/financial-terminal?${params}`);
}

export async function getDriverAssumptions(ticker: string): Promise<DriverAssumption[]> {
  return requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/driver-assumptions`);
}

export async function createDriverAssumption(ticker: string, formData: FormData) {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/driver-assumptions`, {
    method: 'POST',
    body: JSON.stringify({
      driver_key: required(formData, 'driver_key', 'Driver'),
      fiscal_year: Number(required(formData, 'fiscal_year', 'Fiscal year')),
      scenario: String(formData.get('scenario') ?? 'base'),
      value: Number(required(formData, 'value', 'Value')),
      source: required(formData, 'source', 'Source'),
      confidence: Number(formData.get('confidence') ?? 1),
      rationale: required(formData, 'rationale', 'Rationale'),
      user_override: true,
    }),
  });
  revalidatePath(`/research/${ticker.toUpperCase()}/driver-assumptions`);
  revalidatePath(`/research/${ticker.toUpperCase()}`);
}

export async function getDecisionLessons(ticker: string) {
  const normalized = encodeURIComponent(ticker.toUpperCase());
  const [lessons, taxonomy] = await Promise.all([
    requestJson<DecisionLesson[]>(`/api/companies/${normalized}/decision-lessons`),
    requestJson<{ taxonomy: string[] }>(`/api/companies/${normalized}/decision-lessons/taxonomy`),
  ]);
  return { lessons, taxonomy: taxonomy.taxonomy };
}

export async function proposeDecisionLessons(ticker: string) {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/decision-lessons/propose`, { method: 'POST' });
  revalidatePath(`/research/${ticker.toUpperCase()}/decision-lessons`);
}

export async function updateDecisionLesson(ticker: string, lessonId: number, formData: FormData) {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/decision-lessons/${assertPositiveInt(lessonId, 'lessonId')}`, {
    method: 'PUT',
    body: JSON.stringify({
      taxonomy: required(formData, 'taxonomy', 'Taxonomy'),
      cause: required(formData, 'cause', 'Cause'),
      error: required(formData, 'error', 'Error'),
      lesson: required(formData, 'lesson', 'Lesson'),
      future_application: required(formData, 'future_application', 'Future application'),
    }),
  });
  revalidatePath(`/research/${ticker.toUpperCase()}/decision-lessons`);
}

export async function decideDecisionLesson(ticker: string, lessonId: number, action: 'approve' | 'reject') {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/decision-lessons/${assertPositiveInt(lessonId, 'lessonId')}/action`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
  revalidatePath(`/research/${ticker.toUpperCase()}/decision-lessons`);
}

export async function getManagementCredibility(ticker: string): Promise<ManagementCredibility> {
  return requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility`);
}

export async function createManagementPromise(ticker: string, formData: FormData) {
  const target = String(formData.get('target_value') ?? '').trim();
  const sourceDocument = String(formData.get('source_document_id') ?? '').trim();
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility/promises`, {
    method: 'POST',
    body: JSON.stringify({
      promise: required(formData, 'promise', 'Promise'),
      promise_date: required(formData, 'promise_date', 'Promise date'),
      expected_period: required(formData, 'expected_period', 'Expected period'),
      metric: String(formData.get('metric') ?? '').trim() || null,
      operator: String(formData.get('operator') ?? '').trim() || null,
      target_value: target ? Number(target) : null,
      unit: String(formData.get('unit') ?? '').trim() || null,
      source_document_id: sourceDocument ? Number(sourceDocument) : null,
    }),
  });
  revalidatePath(`/research/${ticker.toUpperCase()}/management-credibility`);
}

export async function importManagementCallClaims(ticker: string) {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility/import-call-claims`, { method: 'POST' });
  revalidatePath(`/research/${ticker.toUpperCase()}/management-credibility`);
}

export async function reconcileManagementCredibility(ticker: string) {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility/reconcile`, { method: 'POST' });
  revalidatePath(`/research/${ticker.toUpperCase()}/management-credibility`);
}

export async function updateManagementExplanation(ticker: string, promiseId: number, formData: FormData) {
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility/promises/${promiseId}/explanation`, {
    method: 'PUT',
    body: JSON.stringify({ explanation: required(formData, 'explanation', 'Explanation') }),
  });
  revalidatePath(`/research/${ticker.toUpperCase()}/management-credibility`);
}

export async function getPortfolioIntelligence(years = 5): Promise<PortfolioIntelligence> {
  return requestJson(`/api/portfolio/intelligence?years=${Math.max(1, Math.min(20, years))}`);
}

export async function getKnowledgeGraph(input: { nodeTypes?: string; ticker?: string; limit?: number } = {}): Promise<KnowledgeGraph> {
  const params = new URLSearchParams({ limit: String(Math.max(1, Math.min(500, input.limit ?? 120))) });
  if (input.nodeTypes?.trim()) params.set('node_types', input.nodeTypes.trim());
  if (input.ticker?.trim()) params.set('ticker', input.ticker.trim().toUpperCase());
  return requestJson(`/api/knowledge-graph?${params}`);
}

export async function syncKnowledgeGraph() {
  await requestJson('/api/knowledge-graph/sync', { method: 'POST' });
  revalidatePath('/knowledge-graph');
}

export async function getKnowledgeNeighborhood(nodeId: number, depth = 2): Promise<KnowledgeGraph> {
  return requestJson(`/api/knowledge-graph/nodes/${assertPositiveInt(nodeId, 'nodeId')}/neighbors?depth=${Math.max(1, Math.min(4, depth))}`);
}
