/**
 * Resuelve una promesa con un presupuesto propio: si no contesta a tiempo,
 * se usa el fallback. El temporizador siempre se cancela al asentarse la
 * carrera (en serverless, un timer colgado mantiene la instancia viva).
 *
 * Prod 2026-11-09: /api/market/changes tardó 8-9 s por HTTP y la watchlist
 * lo esperaba en el Promise.all de entrada, así que el cierre datado de
 * respaldo llegaba DESPUÉS de que las filas ya hubieran quedado N/D. La
 * respuesta de respaldo no puede sentarse detrás del mismo cuello que
 * pretende aliviar.
 */
export async function withTimeoutFallback<T>(promise: Promise<T>, budgetMs: number, fallback: T): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
        return await Promise.race([
            promise,
            new Promise<T>((resolve) => {
                timer = setTimeout(() => resolve(fallback), budgetMs);
            }),
        ]);
    } finally {
        if (timer !== undefined) clearTimeout(timer);
    }
}
