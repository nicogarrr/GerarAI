/**
 * Adaptador del buscador universal (/search): traduce la respuesta cruda del
 * motor al contrato que pinta la página y RECHAZA las formas que rompen ese
 * contrato.
 *
 * Motivo (hallazgo 2026-11-08, ref 760826059): el backend respondía 200 y la
 * página reventaba igualmente al pintar (results.map sobre una forma
 * inesperada o un cuerpo vacío): el crash se llevaba la página entera al
 * ErrorBoundary global. Reglas:
 * - Estructura inválida (cuerpo no objeto, results/items no lista, retrieval
 *   o filters no objeto): UniversalSearchContractError. Nunca se pinta como
 *   «sin evidencia» legítimo: la página lo loguea con [search] y muestra el
 *   estado local de error.
 * - Ítems inválidos o incompletos dentro de una lista válida: se filtran o se
 *   coercionan a formas seguras, de modo que el render posterior no puede
 *   lanzar (p. ej. scores ausentes dejaban un TypeError en result.scores).
 */

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

// POST /api/search responde paginado ({ items, page_info, ... }) desde la
// paginación de endpoints; la página /search lee `results` y `total`. Sin este
// adaptador `results` llegaba undefined y la página reventaba al pintar.
export type UniversalSearchWire = {
  query?: unknown;
  status?: unknown;
  filters?: unknown;
  retrieval?: unknown;
  total?: unknown;
  results?: unknown;
  items?: unknown;
  page_info?: unknown;
};

export class UniversalSearchContractError extends Error {
  constructor(detail: string) {
    super(`POST /api/search returned an unexpected shape: ${detail}`);
    this.name = 'UniversalSearchContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/**
 * Un ítem se conserva cuando identifica su entidad (tipo + id); el resto de
 * campos se coercionan para que el JSX no pueda lanzar. Sin identidad no hay
 * nada honesto que pintar: se descarta.
 */
function asResultItem(value: unknown): UniversalSearchResult | null {
  if (!isRecord(value)) return null;
  if (typeof value.entity_type !== 'string' || value.entity_type === '') return null;
  const entityId = asFiniteNumber(value.entity_id);
  if (entityId === null) return null;
  const scores = isRecord(value.scores) ? value.scores : {};
  return {
    entity_type: value.entity_type,
    entity_id: entityId,
    title: asString(value.title),
    text: asString(value.text),
    ticker: asStringOrNull(value.ticker),
    collection: asStringOrNull(value.collection),
    status: asString(value.status),
    source_type: asString(value.source_type),
    source_tier: asString(value.source_tier),
    source_trust: asFiniteNumber(value.source_trust) ?? 0,
    as_of: asStringOrNull(value.as_of),
    citation: asString(value.citation),
    scores: {
      lexical: asFiniteNumber(scores.lexical) ?? 0,
      vector: asFiniteNumber(scores.vector) ?? 0,
      rrf: asFiniteNumber(scores.rrf) ?? 0,
      reranker: asFiniteNumber(scores.reranker) ?? 0,
    },
  };
}

export function toUniversalSearchResponse(raw: unknown): UniversalSearchResponse {
  if (!isRecord(raw)) {
    throw new UniversalSearchContractError('body is not an object');
  }
  const wireList = raw.results ?? raw.items;
  if (wireList !== undefined && wireList !== null && !Array.isArray(wireList)) {
    throw new UniversalSearchContractError('results/items is not a list');
  }
  if (raw.retrieval !== undefined && raw.retrieval !== null && !isRecord(raw.retrieval)) {
    throw new UniversalSearchContractError('retrieval is not an object');
  }
  if (raw.filters !== undefined && raw.filters !== null && !isRecord(raw.filters)) {
    throw new UniversalSearchContractError('filters is not an object');
  }
  const items = Array.isArray(wireList) ? wireList : [];
  const results = items
    .map(asResultItem)
    .filter((item): item is UniversalSearchResult => item !== null);
  const pageInfo = isRecord(raw.page_info) ? raw.page_info : {};
  const total = asFiniteNumber(raw.total) ?? asFiniteNumber(pageInfo.total_items) ?? results.length;
  return {
    query: asString(raw.query),
    ...(typeof raw.status === 'string' ? { status: raw.status } : {}),
    ...(raw.filters !== undefined && raw.filters !== null ? { filters: raw.filters as Record<string, unknown> } : {}),
    retrieval: isRecord(raw.retrieval) ? raw.retrieval : {},
    total,
    results,
  };
}
