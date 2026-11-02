'use server';

import { revalidatePath } from 'next/cache';

import { normalizeResearchBody, researchIdentityHeaders } from '@/lib/auth/research-identity';
import { parseLocalizedNumberDetailed } from '@/lib/format';
import { RESEARCH_TIMEOUTS, requestSignal } from '@/lib/research/client';
import { researchErrorDetail } from '@/lib/research/error-detail';
import { AppError, ExternalAPIError, ValidationError, isNextRedirectError } from '@/lib/types/errors';
import { assertPositiveInt } from '@/lib/validation/pathParams';
import { knowledgeTickerFormValue, libraryReadingsPath } from '@/lib/knowledge/document-ticker';
import { backendMessageForRequest } from '@/lib/research/backend-error-locale';
import type { components } from '@/lib/research/openapi.generated';
import type { ScreenCriterion, ScreenResult } from '@/lib/screener-types';

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
  /** Empresa a la que se refiere el documento (normalizado en mayúsculas) o null. */
  ticker: string | null;
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

export type CustomMetric = components['schemas']['ScreenerCustomMetricOut'];

export type SavedScreen = components['schemas']['ScreenerSavedScreenOut'];

// El contrato del motor de screeners vive en lib/screener-types.ts
// (compartido con screener.actions); se reexporta para sus consumidores.
export type { ScreenCriterion, ScreenResult } from '@/lib/screener-types';

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
    /** Por que falta la metrica, cuando el backend lo sabe decir sin inventar. */
    missing_reason?: string | null;
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

export type PortfolioIntelligence = components['schemas']['PortfolioIntelligenceOut'];

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
    detail = researchErrorDetail(await response.json(), detail);
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

/**
 * Numéricos de formularios de research: el usuario escribe en es-ES
 * («1.234,56», «0,7»). Los formatos ambiguos se rechazan enseñando el
 * formato esperado, nunca se reinterpretan con un factor 1000 silencioso.
 */
function localizedFormNumber(
  formData: FormData,
  key: string,
  label: string,
  options: { required?: boolean; min?: number; max?: number } = {},
): number | null {
  const raw = String(formData.get(key) ?? '').trim();
  if (!raw) {
    if (options.required) throw new ValidationError(`${label} es obligatorio.`, key);
    return null;
  }
  const parsed = parseLocalizedNumberDetailed(raw);
  if (!parsed.ok) {
    throw new ValidationError(
      parsed.error === 'ambiguous'
        ? 'Formato de número ambiguo: usa la coma para los decimales y el punto para los miles (ej. 1.234,56).'
        : `Introduce un valor numérico válido para ${label}.`,
      key,
    );
  }
  const value = parsed.value;
  if ((options.min !== undefined && value < options.min) || (options.max !== undefined && value > options.max)) {
    throw new ValidationError(`${label} debe estar entre ${options.min} y ${options.max}.`, key);
  }
  return value;
}

export async function getKnowledgeLibrary(options: { documentOffset?: number; principleOffset?: number; status?: string; q?: string } = {}) {
  const documentOffset = Number.isSafeInteger(options.documentOffset) && options.documentOffset! >= 0 ? options.documentOffset! : 0;
  const principleOffset = Number.isSafeInteger(options.principleOffset) && options.principleOffset! >= 0 ? options.principleOffset! : 0;
  const status = options.status ? `&status=${encodeURIComponent(options.status)}` : '';
  // Búsqueda por título/autor/ticker en el backend (por tenant y paginada);
  // la página normal sigue dando el total y los recuentos por colección.
  const q = (options.q ?? '').trim().slice(0, 200);
  const [collections, documentPage, principlePage, jobs, search] = await Promise.all([
    requestJson<KnowledgeCollection[]>('/api/knowledge/collections'),
    requestJson<{ items: KnowledgeDocument[]; total: number; collection_counts: Record<string, number> }>(`/api/knowledge/documents/page?limit=${q ? 1 : 50}&offset=${q ? 0 : documentOffset}`),
    requestJson<{ items: InvestmentPrinciple[]; total: number; proposed_total: number }>(`/api/knowledge/principles/page?limit=50&offset=${principleOffset}${status}`),
    requestJson<KnowledgeProcessingJob[]>('/api/knowledge/jobs?limit=100'),
    q
      ? requestJson<{ items: KnowledgeDocument[]; total: number; query: string }>(`/api/knowledge/documents/search?q=${encodeURIComponent(q)}&limit=50&offset=${documentOffset}`)
      : Promise.resolve(null),
  ]);
  return { collections, documents: search ? search.items : documentPage.items, documentTotal: documentPage.total,
    documentSearch: search ? { query: q, total: search.total } : null,
    collectionCounts: documentPage.collection_counts, principles: principlePage.items,
    principleTotal: principlePage.total, proposedTotal: principlePage.proposed_total, jobs };
}

export type CorpusIngestResult = { success: true } | { success: false; message: string };

/** Encola la primera descarga del corpus libre de cartas (202; el actor trabaja en segundo plano). */
export async function ingestLettersCorpusNow(): Promise<CorpusIngestResult> {
  try {
    await requestJson('/api/knowledge/corpus/ingest-async', { method: 'POST' });
    return { success: true };
  } catch (error) {
    console.error('ingestLettersCorpusNow error:', error);
    return { success: false, message: error instanceof Error ? await backendMessageForRequest(error.message) : 'No se pudo encolar la descarga.' };
  }
}

/** Lecturas de la biblioteca enlazadas a un ticker (para la ficha /research/[ticker]). */
export async function getKnowledgeDocumentsForTicker(ticker: string) {
  return requestJson<KnowledgeDocument[]>(libraryReadingsPath(ticker));
}

/** Asigna, cambia o quita (campo vacío) el ticker de un documento de la biblioteca. */
export async function setKnowledgeDocumentTicker(documentId: number, formData: FormData) {
  const ticker = knowledgeTickerFormValue(formData.get('ticker'));
  await requestJson(`/api/knowledge/documents/${assertPositiveInt(documentId, 'documentId')}`, {
    method: 'PATCH',
    body: JSON.stringify({ ticker }),
  });
  revalidatePath('/knowledge');
  if (ticker) revalidatePath(`/research/${encodeURIComponent(ticker)}`);
}

export async function getKnowledgeDocuments() {
  return requestJson<KnowledgeDocument[]>('/api/knowledge/documents?limit=500');
}

/** Cartas listas: filtrar antes de paginar para no ocultarlas tras otros documentos. */
export async function getKnowledgeLetters() {
  const letters: KnowledgeDocument[] = [];
  const seen = new Set<number>();
  const limit = 500;
  for (let offset = 0; ; offset += limit) {
    const page = await requestJson<KnowledgeDocument[]>(
      `/api/knowledge/documents?document_type=fund_letter&status=ready&limit=${limit}&offset=${offset}`,
    );
    if (page.some(doc => seen.has(doc.id))) {
      throw new Error('No se pudo completar el listado de cartas: páginas repetidas.');
    }
    for (const doc of page) seen.add(doc.id);
    letters.push(...page);
    if (page.length < limit) return letters;
  }
}

export type KnowledgeDocumentDetail = KnowledgeDocument & { chunk_count: number };

/** Un documento por id. `null` si no existe (404); cualquier otro error se propaga. */
export type DeleteDocumentResult = { success: true } | { success: false; message: string };

/** Borra un documento de conocimiento (y sus fragmentos) tras confirmación en la UI. */
export async function deleteKnowledgeDocument(documentId: number): Promise<DeleteDocumentResult> {
  try {
    await requestJson(`/api/knowledge/documents/${assertPositiveInt(documentId, 'documentId')}`, { method: 'DELETE' });
    revalidatePath('/knowledge');
    return { success: true };
  } catch (error) {
    console.error('deleteKnowledgeDocument error:', error);
    return { success: false, message: error instanceof Error ? await backendMessageForRequest(error.message) : 'No se pudo eliminar el documento.' };
  }
}

/** Borra una colección VACÍA de conocimiento tras confirmación en la UI. El backend responde 409 si aún tiene documentos. */
export async function deleteKnowledgeCollection(collectionId: number): Promise<DeleteDocumentResult> {
  try {
    await requestJson(`/api/knowledge/collections/${assertPositiveInt(collectionId, 'collectionId')}`, { method: 'DELETE' });
    revalidatePath('/knowledge');
    return { success: true };
  } catch (error) {
    console.error('deleteKnowledgeCollection error:', error);
    return { success: false, message: error instanceof Error ? await backendMessageForRequest(error.message) : 'No se pudo eliminar la colección.' };
  }
}

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
  for (const key of ['collection_id', 'author', 'source_url', 'publication_date', 'ticker']) {
    if (!String(formData.get(key) ?? '').trim()) formData.delete(key);
  }
  await requestJson('/api/knowledge/documents/upload', { method: 'POST', body: formData });
  revalidatePath('/knowledge');
}

/** Resultado de una mutacion de formulario con validacion de negocio. */
export type FormMutationResult =
  | { ok: true }
  | { ok: false; cause: 'validation'; message: string };

/** @deprecated Alias de compatibilidad; usa FormMutationResult. */
export type KnowledgeMutationResult = FormMutationResult;

/**
 * Las validaciones de formulario de la Biblioteca vuelven como RESULTADO,
 * no como throw: en produccion Next enmascara el error lanzado por una
 * server action (mensaje generico + digest) y MutationForm lo clasificaba
 * como motor caido («El motor de analisis no responde…») cuando el problema
 * era el propio formulario (documento sin elegir, nombre vacio). El
 * ValidationError trae `field`; el mensaje en español se decide aqui, en
 * servidor, sin tocar los literales lanzados (contrato del carril B:
 * createAlertResult). El resto de fallos (motor caido, sesion, redirect)
 * sigue lanzando para que el cliente ofrezca reintentar o navegue.
 */
async function formMutationResult(
  action: () => Promise<unknown>,
  fieldMessages: Record<string, string>,
): Promise<FormMutationResult> {
  try {
    await action();
    return { ok: true };
  } catch (error) {
    if (isNextRedirectError(error)) throw error;
    if (error instanceof ValidationError) {
      return {
        ok: false,
        cause: 'validation',
        message: fieldMessages[error.field ?? ''] ?? 'Revisa el formulario: falta un campo obligatorio.',
      };
    }
    throw error;
  }
}

export async function uploadKnowledgeDocumentResult(formData: FormData): Promise<KnowledgeMutationResult> {
  return formMutationResult(() => uploadKnowledgeDocument(formData), {
    file: 'Elige un documento para subir.',
  });
}

export async function createKnowledgeCollectionResult(formData: FormData): Promise<KnowledgeMutationResult> {
  return formMutationResult(() => createKnowledgeCollection(formData), {
    name: 'Ponle un nombre a la colección.',
  });
}

export async function reviseKnowledgePrincipleResult(principleId: number, formData: FormData): Promise<KnowledgeMutationResult> {
  return formMutationResult(() => reviseKnowledgePrinciple(principleId, formData), {
    principle: 'El principio no puede quedar vacío.',
    category: 'Indica la categoría del principio.',
  });
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
  const raw = await requestJson<UniversalSearchWire>('/api/search', {
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
      page_size: 50,
      include_vector: input.includeVector !== false,
    }),
  });
  return toUniversalSearchResponse(raw);
}

// POST /api/search responde paginado ({ items, page_info, ... }) desde la
// paginación de endpoints; la página /search lee `results` y `total`. Sin este
// adaptador `results` llegaba undefined y la página reventaba al pintar.
type UniversalSearchWire = Partial<UniversalSearchResponse> & {
  items?: UniversalSearchResult[];
  page_info?: { total_items?: number };
};

function toUniversalSearchResponse(raw: UniversalSearchWire): UniversalSearchResponse {
  const results = raw.results ?? raw.items ?? [];
  return {
    query: raw.query ?? '',
    ...(raw.status !== undefined ? { status: raw.status } : {}),
    ...(raw.filters !== undefined ? { filters: raw.filters } : {}),
    retrieval: raw.retrieval ?? {},
    total: raw.total ?? raw.page_info?.total_items ?? results.length,
    results,
  };
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

export async function updateSavedScreen(formData: FormData) {
  const id = assertPositiveInt(Number(formData.get('screen_id')), 'screen_id');
  await requestJson(`/api/screeners/screens/${id}`, {
    method: 'PUT',
    body: JSON.stringify({
      name: required(formData, 'name', 'Nombre'),
      description: String(formData.get('description') ?? ''),
      criteria: JSON.parse(required(formData, 'criteria_json', 'Criterios')),
      ranking_formula: String(formData.get('ranking_formula') ?? '').trim() || null,
      ranking_direction: String(formData.get('ranking_direction') ?? 'desc'),
      alerts_enabled: formData.get('alerts_enabled') === 'on',
    }),
  });
  revalidatePath('/screeners');
}

export async function deleteSavedScreen(formData: FormData) {
  if (formData.get('confirm') !== 'on') throw new Error('Confirma que quieres eliminar el filtro.');
  const id = assertPositiveInt(Number(formData.get('screen_id')), 'screen_id');
  await requestJson(`/api/screeners/screens/${id}`, { method: 'DELETE' });
  revalidatePath('/screeners');
}

export async function getScreenerMetricCoverage(): Promise<string[] | null> {
  // Names with data for at least one company; null when the engine cannot
  // answer, so the UI keeps its full static suggestion list instead of
  // offering nothing.
  try {
    const payload = await requestJson<components['schemas']['ScreenerMetricCoverageOut']>('/api/screeners/metric-coverage');
    return Array.isArray(payload.metrics_with_data) ? payload.metrics_with_data : null;
  } catch {
    return null;
  }
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
      value: localizedFormNumber(formData, 'value', 'El valor', { required: true }),
      source: required(formData, 'source', 'Source'),
      confidence: localizedFormNumber(formData, 'confidence', 'La confianza', { min: 0, max: 1 }) ?? 1,
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
  const target = localizedFormNumber(formData, 'target_value', 'El valor objetivo');
  const sourceDocument = String(formData.get('source_document_id') ?? '').trim();
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility/promises`, {
    method: 'POST',
    body: JSON.stringify({
      promise: required(formData, 'promise', 'Promise'),
      promise_date: required(formData, 'promise_date', 'Promise date'),
      expected_period: required(formData, 'expected_period', 'Expected period'),
      metric: String(formData.get('metric') ?? '').trim() || null,
      operator: String(formData.get('operator') ?? '').trim() || null,
      target_value: target,
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
  await requestJson(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/management-credibility/promises/${assertPositiveInt(promiseId, 'promiseId')}/explanation`, {
    method: 'PUT',
    body: JSON.stringify({ explanation: required(formData, 'explanation', 'Explanation') }),
  });
  revalidatePath(`/research/${ticker.toUpperCase()}/management-credibility`);
}

export async function getPortfolioIntelligence(years = 5): Promise<PortfolioIntelligence> {
  return requestJson(`/api/portfolio/intelligence?years=${Math.max(1, Math.min(20, years))}`);
}

export type PortfolioRiskMatrix = components['schemas']['PortfolioRiskMatrixOut'];

/** GET /api/portfolio/risk-matrix — covarianza Ledoit-Wolf y contribución al riesgo por posición. */
export async function getPortfolioRiskMatrix(): Promise<PortfolioRiskMatrix> {
  return requestJson('/api/portfolio/risk-matrix');
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

export async function createCustomMetricResult(formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => createCustomMetric(formData), {
    metric_key: 'Dale una clave a la métrica (p. ej. margen_neto).',
    name: 'Ponle un nombre a la métrica.',
    formula: 'Escribe la fórmula de la métrica.',
  });
}

export async function createSavedScreenResult(formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => createSavedScreen(formData), {
    name: 'Ponle un nombre al filtro.',
    criteria_json: 'Define al menos un criterio.',
    left: 'Cada criterio necesita los dos lados.',
    left_2: 'Cada criterio necesita los dos lados.',
    left_3: 'Cada criterio necesita los dos lados.',
  });
}

export async function updateSavedScreenResult(formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => updateSavedScreen(formData), {
    name: 'Ponle un nombre al filtro.',
  });
}

export async function createDriverAssumptionResult(ticker: string, formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => createDriverAssumption(ticker, formData), {
    driver_key: 'Elige el driver del supuesto.',
    fiscal_year: 'Indica el año fiscal.',
    source: 'Indica la fuente del supuesto.',
    rationale: 'Explica el porqué del supuesto.',
  });
}

export async function updateDecisionLessonResult(ticker: string, lessonId: number, formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => updateDecisionLesson(ticker, lessonId, formData), {
    taxonomy: 'Elige la taxonomía de la lección.',
    cause: 'Describe la causa raíz.',
    error: 'Describe el error de decisión.',
    lesson: 'Escribe la lección duradera.',
    future_application: 'Indica cómo cambia las decisiones futuras.',
  });
}

export async function createManagementPromiseResult(ticker: string, formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => createManagementPromise(ticker, formData), {
    promise: 'Escribe la promesa registrada.',
    promise_date: 'Indica la fecha de la promesa.',
    expected_period: 'Indica el periodo de cumplimiento esperado.',
  });
}

export async function updateManagementExplanationResult(ticker: string, promiseId: number, formData: FormData): Promise<FormMutationResult> {
  return formMutationResult(() => updateManagementExplanation(ticker, promiseId, formData), {
    explanation: 'Escribe la explicación.',
  });
}
