/**
 * F131: el inventario global de fuentes mostraba los 50 documentos más
 * recientes sin forma de llegar al resto (432 en prod). El backend ya pagina
 * y filtra por ticker (`/api/sources/documents` y `/documents/count`):
 * esta lógica concentra la paginación y los enlaces para probarla de verdad.
 */

export const SOURCES_PAGE_SIZE = 50;

/** Alcance del inventario: el universo seguido por el usuario o todo. */
export type SourcesScope = 'universe' | 'all';

export const DEFAULT_SOURCES_SCOPE: SourcesScope = 'universe';

export type SourcesFilters = {
    scope?: SourcesScope;
    sourceType?: string;
    q?: string;
};

/**
 * Normaliza el alcance desde searchParams. Cualquier valor ausente o no
 * reconocido cae en «Mi universo»: el inventario global no es el defecto.
 */
export function normalizeSourcesScope(raw: string): SourcesScope {
    return raw.trim().toLowerCase() === 'all' ? 'all' : DEFAULT_SOURCES_SCOPE;
}

/** source_type es un id interno del backend: se limpia, no se traduce. */
export function normalizeSourcesType(raw: string): string {
    return raw.trim().toLowerCase().replace(/[^a-z0-9_]/g, '').slice(0, 80);
}

/** Texto de búsqueda acotado para no construir URLs desmesuradas. */
export function normalizeSourcesQuery(raw: string): string {
    return raw.replace(/\s+/g, ' ').trim().slice(0, 120);
}

export type SourcesPageInfo = {
    /** Página efectiva, 1-based y acotada entre 1 y `pages`. */
    page: number;
    /** Total de páginas (al menos 1). */
    pages: number;
    /** Posición 1-based del primer documento visible (0 si no hay). */
    from: number;
    /** Posición del último visible (inclusive). */
    to: number;
};

export function sourcesPageInfo(total: number, requestedPage: number, pageSize: number = SOURCES_PAGE_SIZE): SourcesPageInfo {
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(Math.max(1, requestedPage), pages);
    const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const to = Math.min(page * pageSize, total);
    return { page, pages, from, to };
}

/** Enlace del inventario conservando ticker, alcance, tipo y búsqueda. */
export function sourcesHref(
    ticker: string,
    page: number,
    filters: SourcesFilters = {},
): string {
    const params = new URLSearchParams();
    const clean = normalizeSourcesTicker(ticker);
    if (clean) params.set('ticker', clean);
    if (filters.scope) params.set('scope', filters.scope);
    if (filters.sourceType) params.set('source_type', filters.sourceType);
    const query = filters.q ? normalizeSourcesQuery(filters.q) : '';
    if (query) params.set('q', query);
    if (page > 1) params.set('page', String(page));
    const qs = params.toString();
    return qs ? `/research/sources?${qs}` : '/research/sources';
}

/**
 * searchParams puede repetir una clave (?ticker=A&ticker=B) y Next la
 * entrega como array; sin normalizar rompe la página. Primer valor.
 */
export function firstSearchParam(raw: string | string[] | undefined): string {
    const value = Array.isArray(raw) ? raw[0] : raw;
    return typeof value === 'string' ? value : '';
}

/** Normaliza el filtro de ticker desde searchParams ('' = sin filtro). */
export function normalizeSourcesTicker(raw: string): string {
    return raw.trim().toUpperCase();
}
