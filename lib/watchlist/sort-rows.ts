/**
 * Orden final de las filas de la watchlist una vez cotizadas.
 *
 * - «added» (por defecto): respeta el orden del backend (recientes primero)
 *   y solo hunde al final las filas sin precio.
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
