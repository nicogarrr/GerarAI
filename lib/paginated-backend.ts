/**
 * Lectura COMPLETA de un endpoint paginado `page`/`page_size` del backend
 * (respuesta `{ items, page_info }`). Pide páginas de BACKEND_PAGE_SIZE hasta
 * la primera página corta.
 *
 * Veracidad: si se alcanza MAX_PAGES con la última página llena se LANZA
 * error en lugar de devolver la lista parcial rotulada como completa (misma
 * regla que lib/paginate-all.ts para endpoints limit/offset). Un array pelado
 * (contrato antiguo) se acepta solo como defensa en runtime.
 */

export type PaginatedBackendResponse<T> = { items: T[]; page_info?: unknown };

/** Máximo que acepta el backend: page_size Query(le=200) en las rutas paginadas. */
export const BACKEND_PAGE_SIZE = 200;

/** Válvula de escape: 25 páginas × 200 = 5.000 elementos. No es un límite
 * esperado (carteras de una persona), es el freno ante un backend que no
 * avanza o un bucle de páginas repetidas. */
const MAX_PAGES = 25;

export async function fetchAllBackendPages<T>(
    fetchPage: (page: number) => Promise<PaginatedBackendResponse<T> | T[] | null | undefined>,
): Promise<T[]> {
    const all: T[] = [];
    for (let page = 1; ; page += 1) {
        const res = await fetchPage(page);
        // Forma malformada (sin items) no es una página vacía: es un backend
        // roto. Lanzar, no disfrazarla de lista vacía.
        if (res != null && !Array.isArray(res) && !Array.isArray((res as PaginatedBackendResponse<T>).items)) {
            throw new Error('fetchAllBackendPages: respuesta sin items; el backend no cumple el contrato paginado');
        }
        const items = Array.isArray(res) ? res : res?.items ?? [];
        all.push(...items);
        if (items.length < BACKEND_PAGE_SIZE) return all;
        if (page >= MAX_PAGES) {
            throw new Error(
                `fetchAllBackendPages: ${MAX_PAGES} páginas llenas (${MAX_PAGES * BACKEND_PAGE_SIZE} elementos) y el backend no agota la lista; no se entrega una lista parcial como completa`,
            );
        }
    }
}
