/**
 * Pagina un endpoint `limit`/`offset` hasta agotarlo, con salida adversa
 * explícita: si el backend (o un proxy intermedio) ignora `offset`, cada
 * página repite contenido y un bucle «hasta página corta» no terminaría
 * nunca, colgando la petición y acumulando memoria. En cuanto una página
 * no progresa (su primer elemento ya abrió una página anterior) se lanza
 * error: NUNCA se devuelve una lista parcial que la interfaz pudiera
 * rotular como completa.
 *
 * Rendimiento: las páginas se piden en OLEADAS PARALELAS. Antes cada página
 * esperaba a la anterior (5 páginas de /api/companies ≈ 1 s de render de
 * /research en cadena); ahora la primera página sale sola y las siguientes
 * de 4 en 4 a la vez. El contrato no cambia: se devuelven TODAS las páginas
 * hasta la primera corta, en orden, y la guarda de página repetida sigue
 * lanzando error.
 */

/** Páginas pedidas a la vez tras la primera. */
const PARALLEL_WAVE = 4;

export async function paginateAll<T>(
    fetchPage: (offset: number) => Promise<T[]>,
    pageSize: number,
    firstKey: (item: T) => string,
): Promise<T[]> {
    const all: T[] = [];
    const seenFirstKeys = new Set<string>();
    const firstPage = await fetchPage(0);
    const firstItem = firstPage[0];
    if (firstItem !== undefined) seenFirstKeys.add(firstKey(firstItem));
    all.push(...firstPage);
    if (firstPage.length < pageSize) return all;

    for (let offset = pageSize; ; offset += PARALLEL_WAVE * pageSize) {
        const pages = await Promise.all(
            Array.from({ length: PARALLEL_WAVE }, (_, i) => fetchPage(offset + i * pageSize)),
        );
        for (const page of pages) {
            const first = page[0];
            if (first !== undefined) {
                const key = firstKey(first);
                if (seenFirstKeys.has(key)) {
                    throw new Error(
                        'paginateAll: el backend no avanza con offset (página repetida); índice incompleto',
                    );
                }
                seenFirstKeys.add(key);
            }
            all.push(...page);
            if (page.length < pageSize) return all;
        }
    }
}
