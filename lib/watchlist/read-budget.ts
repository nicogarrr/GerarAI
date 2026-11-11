/**
 * Presupuestos de lectura de una fila de la watchlist (y de su vista previa en Inicio).
 *
 * La página corta cada fila a los `WATCHLIST_ROW_BUDGET_MS` (3 s) y, pasado el
 * corte, la fila sale vacía con «la lectura tardó más de 3 s». Antes ese corte
 * era el ÚNICO: la cotización (Finnhub → respaldo Yahoo, hasta 5 s por símbolo
 * en frío) y la lectura de /api/watchlist/metrics (cap y PER de la propia base,
 * rápida) iban en el mismo `Promise.all`, así que una cotización lenta tiraba
 * también la capitalización y el PER que el backend ya había devuelto.
 *
 * Ahora cada lectura tiene su propio tope, por debajo del de la fila:
 * - cotización y métricas Finnhub: `WATCHLIST_QUOTE_BUDGET_MS`; si no llegan, la
 *   fila sigue con las cifras del backend y el precio sale del cierre datado
 *   (o «tardó más de…» si tampoco lo hay), marcado `quoteTimedOut`.
 * - backend: hasta `WATCHLIST_BACKEND_DEADLINE_MS` desde el inicio de la fila;
 *   si no llega, `metricsReadFailed` («no se pudo leer a tiempo»), nunca «la
 *   fuente no lo facilita».
 * Mismas reglas para todas las empresas; las lecturas cortadas siguen en vuelo
 * y calientan las cachés para la siguiente carga.
 */

export const WATCHLIST_ROW_BUDGET_MS = 3000;
export const WATCHLIST_QUOTE_BUDGET_MS = 2000;
/** Margen bajo el corte de la fila para que la entrada devuelta llegue antes que él. */
export const WATCHLIST_BACKEND_DEADLINE_MS = 2800;

export type BudgetedRead<T> = { value: T | null; timedOut: boolean };

/**
 * `promise` con tope de `ms`: `{ value, timedOut: false }` si llega a tiempo
 * (un rechazo se propaga, igual que sin tope) y `{ value: null, timedOut: true }`
 * si no. El temporizador se limpia siempre (no mantiene viva la instancia).
 */
export function withinBudget<T>(promise: Promise<T>, ms: number): Promise<BudgetedRead<T>> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    return Promise.race([
        promise.then((value) => ({ value, timedOut: false })),
        new Promise<BudgetedRead<T>>((resolve) => {
            timer = setTimeout(() => resolve({ value: null, timedOut: true }), Math.max(0, ms));
        }),
    ]).finally(() => {
        if (timer) clearTimeout(timer);
    });
}
