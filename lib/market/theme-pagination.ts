import type { ThemeOrder } from '@/lib/market/themes';

/** Temas por página en /temas. Paginación real (?pagina=N), sin scroll infinito. */
export const THEMES_PAGE_SIZE = 6;

/** Página pedida en la URL: entero >= 1; cualquier otra cosa vale 1. */
export function parseThemePage(raw: string | string[] | undefined): number {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string' || !/^\d{1,6}$/.test(value)) return 1;
  const page = Number(value);
  return page >= 1 ? page : 1;
}

export type ThemePage<T> = { items: T[]; page: number; pages: number; total: number };

/** Corta la lista; una página fuera de rango se lleva a la última (nunca vacía). */
export function paginateThemes<T>(items: readonly T[], requestedPage: number, size: number = THEMES_PAGE_SIZE): ThemePage<T> {
  const total = items.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const page = Math.min(Math.max(1, Math.trunc(requestedPage) || 1), pages);
  return { items: items.slice((page - 1) * size, page * size), page, pages, total };
}

/** URL de una página conservando el orden; la página 1 no lleva parámetro. */
export function themePageHref(order: ThemeOrder, page: number): string {
  const params = new URLSearchParams();
  if (order !== 'ytd') params.set('orden', order);
  if (page > 1) params.set('pagina', String(page));
  const query = params.toString();
  return query ? `/temas?${query}` : '/temas';
}
