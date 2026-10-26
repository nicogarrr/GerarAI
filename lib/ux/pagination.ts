/**
 * Paginación local en cliente: 10 elementos por página, sin scroll infinito.
 * Funciones puras para poder probar el corte, el acotado y el rango visible
 * sin montar React.
 */

export const DEFAULT_PAGE_SIZE = 10;

export type PageSlice<T> = {
  /** Página efectiva, 1-based y acotada entre 1 y `pages`. */
  page: number;
  /** Total de páginas (al menos 1, incluso sin elementos). */
  pages: number;
  /** Elementos de la página efectiva. */
  items: T[];
  /** Posición 1-based del primer elemento visible (0 si no hay). */
  from: number;
  /** Posición del último elemento visible (inclusive). */
  to: number;
};

function normalizePageSize(pageSize: number): number {
  if (!Number.isFinite(pageSize)) return DEFAULT_PAGE_SIZE;
  return Math.max(1, Math.floor(pageSize));
}

export function pageCount(totalItems: number, pageSize: number = DEFAULT_PAGE_SIZE): number {
  if (!Number.isFinite(totalItems) || totalItems <= 0) return 1;
  return Math.max(1, Math.ceil(totalItems / normalizePageSize(pageSize)));
}

export function clampPage(requestedPage: number, pages: number): number {
  const safePages = Math.max(1, Number.isFinite(pages) ? Math.floor(pages) : 1);
  if (!Number.isFinite(requestedPage)) return 1;
  return Math.min(Math.max(1, Math.floor(requestedPage)), safePages);
}

export function paginateItems<T>(
  items: T[],
  requestedPage: number,
  pageSize: number = DEFAULT_PAGE_SIZE,
): PageSlice<T> {
  const size = normalizePageSize(pageSize);
  const pages = pageCount(items.length, size);
  const page = clampPage(requestedPage, pages);
  const start = (page - 1) * size;
  const pageItems = items.slice(start, start + size);
  return {
    page,
    pages,
    items: pageItems,
    from: items.length === 0 ? 0 : start + 1,
    to: start + pageItems.length,
  };
}

export function pageLabel(page: number, pages: number): string {
  return `Página ${page} de ${pages}`;
}
