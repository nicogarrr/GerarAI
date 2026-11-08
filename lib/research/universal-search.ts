/**
 * Adaptador del buscador universal (/search): traduce la respuesta cruda del
 * motor al contrato que pinta la página y RECHAZA las formas que rompen ese
 * contrato.
 *
 * Motivo (hallazgo 2026-11-08, ref 760826059): el backend respondía 200 y la
 * página reventaba igualmente al pintar (results.map sobre una forma
 * inesperada o un cuerpo vacío): el crash se llevaba la página entera al
 * ErrorBoundary global. Reglas de veracidad (nada de ceros inventados):
 * - El cuerpo debe ser un objeto con una LISTA real (`results` o `items`;
 *   una lista vacía sí es un cero legítimo). Cualquier otra forma es
 *   UniversalSearchContractError: la página lo loguea con [search] y muestra
 *   el estado local de error, nunca un «sin evidencia» falso.
 * - Un ítem inválido dentro de la lista es corrupción de datos, no un cero:
 *   UniversalSearchContractError, nunca un filtrado silencioso.
 * - Las métricas ausentes (source_trust, scores) se propagan como null y la
 *   ficha las pinta como N/D explícito; nunca se inventa un 0.
 */

export type UniversalSearchScores = {
  lexical: number | null;
  vector: number | null;
  rrf: number | null;
  reranker: number | null;
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
  source_trust: number | null;
  as_of: string | null;
  citation: string;
  scores: UniversalSearchScores;
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
 * Un ítem válido identifica su entidad (tipo + id). Las métricas que faltan
 * quedan en null (la ficha las pinta N/D); un ítem que no es objeto o no
 * identifica su entidad es corrupción: se rechaza la respuesta entera, no se
 * filtra en silencio.
 */
function asResultItem(value: unknown): UniversalSearchResult {
  if (!isRecord(value)) {
    throw new UniversalSearchContractError('a result item is not an object');
  }
  const entityId = asFiniteNumber(value.entity_id);
  if (typeof value.entity_type !== 'string' || value.entity_type === '' || entityId === null) {
    throw new UniversalSearchContractError('a result item lacks entity_type/entity_id');
  }
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
    source_trust: asFiniteNumber(value.source_trust),
    as_of: asStringOrNull(value.as_of),
    citation: asString(value.citation),
    scores: {
      lexical: asFiniteNumber(scores.lexical),
      vector: asFiniteNumber(scores.vector),
      rrf: asFiniteNumber(scores.rrf),
      reranker: asFiniteNumber(scores.reranker),
    },
  };
}

export function toUniversalSearchResponse(raw: unknown): UniversalSearchResponse {
  if (!isRecord(raw)) {
    throw new UniversalSearchContractError('body is not an object');
  }
  for (const key of ['results', 'items'] as const) {
    if (raw[key] !== undefined && raw[key] !== null && !Array.isArray(raw[key])) {
      throw new UniversalSearchContractError(`${key} is not a list`);
    }
  }
  if (raw.retrieval !== undefined && raw.retrieval !== null && !isRecord(raw.retrieval)) {
    throw new UniversalSearchContractError('retrieval is not an object');
  }
  if (raw.filters !== undefined && raw.filters !== null && !isRecord(raw.filters)) {
    throw new UniversalSearchContractError('filters is not an object');
  }
  const wireList = Array.isArray(raw.results) ? raw.results : Array.isArray(raw.items) ? raw.items : null;
  if (wireList === null) {
    throw new UniversalSearchContractError('body without a results list');
  }
  const results = wireList.map(asResultItem);
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
