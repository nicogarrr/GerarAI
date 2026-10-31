/**
 * Lectura COMPLETA de un endpoint paginado `page`/`page_size` del backend
 * (respuesta `{ items, page_info }`). Criterio de parada: `page_info.has_next`
 * del backend; si `page_info` no llega, la regla de respaldo es la primera
 * página corta (< BACKEND_PAGE_SIZE).
 *
 * Reglas de veracidad (todas lanzan, nunca entregan una parcial como completa):
 * - Página repetida (su primer elemento ya abrió otra página): el backend o un
 *   proxy no avanza; misma guarda que lib/paginate-all.ts.
 * - Respuesta null/undefined o sin `items` en cualquier página: backend roto,
 *   no «lista vacía».
 * - MAX_PAGES páginas llenas sin agotar: válvula ante un backend en bucle.
 * Un array pelado (contrato antiguo) se acepta como defensa en runtime.
 */

export type BackendPageInfo = {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
};

export type PaginatedBackendResponse<T> = { items: T[]; page_info?: BackendPageInfo };

/** Máximo que acepta el backend: page_size Query(le=200) en las rutas paginadas. */
export const BACKEND_PAGE_SIZE = 200;

/** Válvula de escape: 25 páginas × 200 = 5.000 elementos. No es un límite
 * esperado (carteras de una persona), es el freno ante un backend que no
 * avanza. */
const MAX_PAGES = 25;

export async function fetchAllBackendPages<T>(
    fetchPage: (page: number) => Promise<PaginatedBackendResponse<T> | T[] | null | undefined>,
    firstKey: (item: T) => string,
): Promise<T[]> {
    const all: T[] = [];
    const seenFirstKeys = new Set<string>();
    for (let page = 1; ; page += 1) {
        const res = await fetchPage(page);
        if (Array.isArray(res)) {
            // Contrato antiguo (lista pelada): solo válido como primera y
            // única página; a mitad de serie sería una página repetida.
            if (page > 1) {
                throw new Error('fetchAllBackendPages: página sin envoltura paginada a mitad de serie; el backend no cumple el contrato');
            }
            return [...res];
        }
        if (res == null || !Array.isArray((res as PaginatedBackendResponse<T>).items)) {
            throw new Error(`fetchAllBackendPages: página ${page} sin items; el backend no cumple el contrato paginado`);
        }
        const { items, page_info: pageInfo } = res;
        const first = items[0];
        if (first !== undefined) {
            const key = firstKey(first);
            if (seenFirstKeys.has(key)) {
                throw new Error(
                    `fetchAllBackendPages: página ${page} repite el primer elemento de una página anterior; el backend no avanza, lista incompleta`,
                );
            }
            seenFirstKeys.add(key);
        }
        all.push(...items);
        if (pageInfo ? !pageInfo.has_next : items.length < BACKEND_PAGE_SIZE) return all;
        if (page >= MAX_PAGES) {
            throw new Error(
                `fetchAllBackendPages: ${MAX_PAGES} páginas (${MAX_PAGES * BACKEND_PAGE_SIZE} elementos) y has_next sigue a true; no se entrega una lista parcial como completa`,
            );
        }
    }
}
