/**
 * Adaptador del buscador universal (/search): traduce la respuesta cruda del
 * motor al contrato que pinta la página y COERCE las formas hostiles.
 *
 * Motivo (hallazgo 2026-11-08, ref 760826059): el backend respondía 200 y la
 * página reventaba igualmente al pintar (`results.map` sobre una forma
 * inesperada o un cuerpo vacío): el crash se llevaba la página entera al
 * ErrorBoundary global. Aquí cualquier respuesta no conforme degrada a una
 * lista vacía honesta en lugar de a un TypeError.
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
export type UniversalSearchWire = Partial<UniversalSearchResponse> & {
  items?: unknown;
  page_info?: { total_items?: unknown } | null;
};

function asResultList(value: unknown): UniversalSearchResult[] {
  return Array.isArray(value) ? (value as UniversalSearchResult[]) : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function toUniversalSearchResponse(raw: UniversalSearchWire | null): UniversalSearchResponse {
  const source: UniversalSearchWire = raw !== null && typeof raw === 'object' ? raw : {};
  const results = asResultList(source.results ?? source.items);
  const total = asCount(source.total) ?? asCount(source.page_info?.total_items) ?? results.length;
  return {
    query: typeof source.query === 'string' ? source.query : '',
    ...(typeof source.status === 'string' ? { status: source.status } : {}),
    ...(source.filters !== undefined ? { filters: asRecord(source.filters) } : {}),
    retrieval: asRecord(source.retrieval),
    total,
    results,
  };
}
