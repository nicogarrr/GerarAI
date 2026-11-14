/**
 * Orden final de las filas de la watchlist una vez cotizadas.
 *
 * - «added» (por defecto): con streaming (decisión de diseño, 2026-11-14)
 *   la página pinta
 *   en el orden del backend (recientes primero) desde el primer byte y cada
 *   fila se repinta EN EL SITIO cuando llega su cotización: una fila sin
 *   precio YA NO se hunde al final. Reordenar tras el pintado movería filas
 *   bajo el dedo en móvil (cambio de layout y toques erróneos). El hundido
 *   de N/D de abajo solo aplica cuando las filas llegan ya resueltas.
 * - «added» con filas resueltas (p. ej. ruta con orden por métrica):
 *   respeta el orden del backend y solo hunde al final las filas sin precio.
 * - «symbol»: los items ya llegan ordenados alfabéticamente; aquí NO se toca
 *   el orden, para que una fila sin precio no rompa el alfabeto.
 * - Métricas: ordena por el valor y deja los N/D siempre al final, en
 *   cualquier dirección.
 *
 * Array.prototype.sort es estable, así que los empates conservan el orden
 * de entrada.
 */
export type WatchlistRowSort = 'added' | 'symbol' | 'price' | 'change' | 'marketCap' | 'pe' | 'earnings';

export function sortWatchlistRows<T extends { price: number | null }>(
    rows: readonly T[],
    sort: WatchlistRowSort,
    dir: 'asc' | 'desc',
    metricValue: (row: T) => number | string | null,
): T[] {
    if (sort === 'symbol') return [...rows];
    if (sort === 'added') {
        return [...rows].sort((a, b) => Number(a.price === null) - Number(b.price === null));
    }
    return [...rows].sort((a, b) => {
        const va = metricValue(a);
        const vb = metricValue(b);
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        const cmp = typeof va === 'string' && typeof vb === 'string' ? va.localeCompare(vb) : Number(va) - Number(vb);
        return dir === 'asc' ? cmp : -cmp;
    });
}
