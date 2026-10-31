/**
 * Batching cliente de server actions por símbolo.
 *
 * Las filas de /watchlist (y otras listas) se montan en el mismo commit y
 * cada una pedía su propio server action (getExtendedQuote, analyst
 * targets...): 12 filas = 12 invocaciones serverless por tipo de dato,
 * el patrón que agota la CPU activa del plan Hobby de Vercel. Medido en
 * prod (31-oct-2026): 24 POSTs de acción por carga de /watchlist.
 *
 * Este planificador acumula las claves pedidas en una ventana corta y las
 * resuelve con UNA llamada batch por tipo de dato; cada fila recibe su
 * valor y requestCache sigue deduplicando por símbolo como antes.
 */

type Resolver<T> = { resolve: (value: T | null) => void; reject: (error: unknown) => void };

type Scheduler<K, V> = {
    pending: Map<K, Resolver<V>[]>;
    timer: ReturnType<typeof setTimeout> | null;
};

const schedulers = new Map<string, Scheduler<unknown, unknown>>();

/** Ventana para juntar las filas que montan en ráfaga (commit + lazy chunks). */
const BATCH_WINDOW_MS = 60;
/** Techo defensivo: nunca mandamos una lista abierta al servidor. */
const BATCH_MAX_KEYS = 100;

/**
 * Pide el valor de una clave dentro del batch `batchId`. Las llamadas que
 * llegan dentro de la ventana se agrupan en una sola invocación de
 * `fetchBatch`, que debe devolver un mapa clave -> valor (null si falta).
 */
export function batchedSymbol<K extends string, V>(
    batchId: string,
    key: K,
    fetchBatch: (keys: K[]) => Promise<Record<string, V | null>>,
): Promise<V | null> {
    let scheduler = schedulers.get(batchId) as Scheduler<K, V> | undefined;
    if (!scheduler) {
        scheduler = { pending: new Map(), timer: null };
        schedulers.set(batchId, scheduler as Scheduler<unknown, unknown>);
    }
    const s = scheduler;
    return new Promise<V | null>((resolve, reject) => {
        const waiters = s.pending.get(key) ?? [];
        waiters.push({ resolve, reject });
        s.pending.set(key, waiters);
        if (s.timer) return;
        s.timer = setTimeout(() => {
            s.timer = null;
            const batch = s.pending;
            s.pending = new Map();
            const keys = [...batch.keys()].slice(0, BATCH_MAX_KEYS);
            const overflow = [...batch.keys()].slice(BATCH_MAX_KEYS);
            for (const k of overflow) {
                for (const w of batch.get(k) ?? []) w.resolve(null);
                batch.delete(k);
            }
            fetchBatch(keys)
                .then((map) => {
                    for (const [k, ws] of batch) {
                        for (const w of ws) w.resolve(map[k] ?? null);
                    }
                })
                .catch((error) => {
                    for (const ws of batch.values()) {
                        for (const w of ws) w.reject(error);
                    }
                });
        }, BATCH_WINDOW_MS);
    });
}

/** Solo para tests: descarta planificadores y temporizadores vivos. */
export function resetBatchedSymbolsForTests(): void {
    for (const s of schedulers.values()) {
        if (s.timer) clearTimeout(s.timer);
        s.pending.clear();
    }
    schedulers.clear();
}
