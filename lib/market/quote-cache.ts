/**
 * Caché en proceso de cotizaciones PÚBLICAS de mercado, con dedupe de
 * fetches concurrentes, concurrencia realmente acotada y respeto de
 * Retry-After del proveedor.
 *
 * Alcance y límites deliberados:
 * - Solo dato de mercado PÚBLICO: la clave es el símbolo normalizado
 *   (trim + mayúsculas) y el valor la cotización saneada. Ningún dato de
 *   usuario entra en esta capa: la tenencia es segura por construcción.
 * - NO protege la cuota global por sí sola: acota el gasto por REPETICIÓN
 *   (mismo símbolo, ráfagas, refrescos, re-renders) a ~1 fetch por símbolo
 *   y TTL. Con muchos símbolos distintos el gasto sigue siendo lineal.
 * - Concurrencia ACOTADA DE VERDAD: como mucho maxInflight fetches en
 *   curso. Al saturarse NO se abre una vía de fanout: el llamador recibe
 *   un resultado degradado explícito { saturated: true, quote: null,
 *   fetchFailed: true } sin fetch nuevo, inmediato (no bloquea el ledger)
 *   y sin maquillar dato viejo como reciente. El llamador puede reintentar
 *   en la siguiente pasada; saturated distingue saturación LOCAL de fallo
 *   del proveedor.
 * - Timeout por fetch (10 s): aborta con AbortSignal (la señal llega al
 *   fetch real cuando el fetcher la propaga) y cuenta como fallo. El SLOT
 *   de concurrencia se conserva hasta que el fetcher asienta de verdad:
 *   si ignora la señal y sigue vivo, no se solapa trabajo nuevo (la
 *   petición zombi puede seguir en el cable; límite documentado). La
 *   respuesta tardía nunca se cachea.
 * - Frescura: al servir desde caché se RE-VALIDA con el reloj ACTUAL
 *   (classifyQuoteKind): si cruzó a 'stale' (cambio de sesión, dato que
 *   envejece durante el TTL) se descarta y se pide de nuevo, nunca se
 *   sirve. Una cotización de cierre NO se asume inmutable (el proveedor
 *   corrige): mismo TTL que cualquier otra. El coste de frescura real es
 *   el movimiento del precio durante el TTL, acotado por parámetro.
 * - Fallos sin envenenamiento: solo se cachean ÉXITOS saneados (nunca una
 *   cotización ya 'stale'). Un fallo —incluidos rechazo del fetcher y
 *   timeout— no guarda valor; solo anota la ventana de reintento
 *   (Retry-After acotado o backoff exponencial acotado) en un mapa
 *   TAMBIÉN acotado (maxFailureMarks), para que los reintentos no
 *   estampiden. Dedupe ≠ backoff: llamadas concurrentes al mismo símbolo
 *   comparten UN fetch; los reintentos esperan su ventana.
 * - Robustez numérica: opciones, retryAfter, reloj y backoff se fuerzan a
 *   finitos (nada de Infinity/NaN); el contador de fallos topea en 32.
 * - El llamador fija asOf: esta capa devuelve fetchedAt REAL de cada
 *   cotización (cuándo salió del proveedor, venga de caché o no); la
 *   valoración debe usar min(fetchedAt) si quiere un asOf honesto bajo
 *   caché (cambio de semántica a documentar en el punto de cableado).
 *
 * Cableado previsto (cuando el carril contable libere actions):
 * getManualDemoValuation llama getQuote(symbol, finnhubOnlyQuote) en vez de
 * finnhubOnlyQuote a pelo. Una instancia compartida por proceso.
 */

import { classifyQuoteKind, type SanitizedQuote } from '@/lib/market/quote-freshness';

/** Intento de cotización tal como lo produce el fetcher del llamador. */
export type QuoteFetchAttempt = {
    quote: SanitizedQuote | null;
    fetchFailed: boolean;
    retryAfterSeconds: number | null;
};

export type CachedQuote = QuoteFetchAttempt & {
    /** Epoch ms en que el proveedor entregó el dato (también si viene de caché). null sin quote. */
    fetchedAt: number | null;
    /** true = saturación LOCAL de concurrencia (sin fetch); false en cualquier otro desenlace. */
    saturated: boolean;
};

export type QuoteCacheOptions = {
    /** Vida máxima de una cotización cacheada. Defecto 20 s. */
    ttlMs?: number;
    /** Máximo de símbolos cacheados; al superarlo se expulsa el más viejo. Defecto 500. */
    maxEntries?: number;
    /** Máximo de fetches en curso; al saturarse, resultado degradado sin fetch. Defecto 100. */
    maxInflight?: number;
    /** Timeout por fetch; al cumplirse cuenta como fallo y se ignora la respuesta tardía. Defecto 10 s. */
    fetchTimeoutMs?: number;
    /** Máximo de marcas anti-estampida; al superarlo se expulsa la que expira antes. Defecto 500. */
    maxFailureMarks?: number;
    /** Tope al Retry-After del proveedor que se respeta. Defecto 300 s. */
    maxRetryAfterSeconds?: number;
    /** Backoff propio sin Retry-After: base y tope. Defectos 1 s y 60 s. */
    failureBackoffBaseMs?: number;
    failureBackoffCapMs?: number;
    /** Reloj inyectable (fixtures). */
    now?: () => number;
};

type Entry = { quote: SanitizedQuote; fetchedAt: number };
type FailureMark = { notBefore: number; failures: number };

export type QuoteCache = {
    /**
     * fetcher recibe (símbolo normalizado, AbortSignal): DEBE propagar la
     * señal al fetch subyacente para que el timeout cancele de verdad.
     * Si la ignora, el slot sigue ocupado hasta que asiente (no hay
     * solape de trabajo nuevo), pero la petición sigue viva en el cable.
     */
    getQuote(symbol: string, fetcher: (symbol: string, signal: AbortSignal) => Promise<QuoteFetchAttempt>): Promise<CachedQuote>;
    /** Nº de cotizaciones cacheadas (introspección para pruebas y métricas). */
    size(): number;
    /** Nº de operaciones de red reales sin asentar (incluye zombis tras timeout). */
    inflightSize(): number;
    /** Nº de marcas anti-estampida activas. */
    failureSize(): number;
};

/** Entero finito >= min; cualquier basura (Infinity, NaN, negativo) cae al defecto. */
const clampInt = (value: number | undefined, fallback: number, min: number): number =>
    typeof value === 'number' && Number.isFinite(value) && value >= min ? Math.floor(value) : fallback;

export function createQuoteCache(options: QuoteCacheOptions = {}): QuoteCache {
    const ttlMs = clampInt(options.ttlMs, 20_000, 0);
    const maxEntries = clampInt(options.maxEntries, 500, 1);
    const maxInflight = clampInt(options.maxInflight, 100, 1);
    const fetchTimeoutMs = clampInt(options.fetchTimeoutMs, 10_000, 1);
    const maxFailureMarks = clampInt(options.maxFailureMarks, 500, 1);
    const maxRetryAfterSeconds = clampInt(options.maxRetryAfterSeconds, 300, 0);
    const backoffBaseMs = clampInt(options.failureBackoffBaseMs, 1_000, 1);
    const backoffCapMs = clampInt(options.failureBackoffCapMs, 60_000, 1);
    const clock = options.now ?? (() => Date.now());
    const now = (): number => {
        const v = clock();
        return Number.isFinite(v) ? v : Date.now();
    };

    const entries = new Map<string, Entry>();
    const inflight = new Map<string, { promise: Promise<CachedQuote>; token: object }>();
    const failureMarks = new Map<string, FailureMark>();
    /** Operaciones de red REALES sin asentar (incluye zombis tras timeout). Cota efectiva. */
    let activeOps = 0;

    const evictEntryOverflow = () => {
        while (entries.size > maxEntries) {
            let oldestKey: string | null = null;
            let oldestAt = Infinity;
            for (const [key, entry] of entries) {
                if (entry.fetchedAt < oldestAt) {
                    oldestAt = entry.fetchedAt;
                    oldestKey = key;
                }
            }
            if (oldestKey === null) return;
            entries.delete(oldestKey);
        }
    };

    const evictMarkOverflow = () => {
        while (failureMarks.size > maxFailureMarks) {
            let soonestKey: string | null = null;
            let soonestAt = Infinity;
            for (const [key, mark] of failureMarks) {
                if (mark.notBefore < soonestAt) {
                    soonestAt = mark.notBefore;
                    soonestKey = key;
                }
            }
            if (soonestKey === null) return;
            failureMarks.delete(soonestKey);
        }
    };

    /** Normaliza el intento del fetcher: retryAfter finito, no negativo, acotado. */
    const sanitizeAttempt = (attempt: QuoteFetchAttempt): QuoteFetchAttempt => ({
        quote: attempt.quote ?? null,
        fetchFailed: attempt.fetchFailed === true,
        retryAfterSeconds:
            typeof attempt.retryAfterSeconds === 'number' && Number.isFinite(attempt.retryAfterSeconds) && attempt.retryAfterSeconds >= 0
                ? Math.min(Math.floor(attempt.retryAfterSeconds), maxRetryAfterSeconds)
                : null,
    });

    /** Registra el resultado UNA vez (solo quien hizo el fetch real o su timeout). */
    const settle = (key: string, rawAttempt: QuoteFetchAttempt, at: number): CachedQuote => {
        const attempt = sanitizeAttempt(rawAttempt);
        if (!attempt.fetchFailed && attempt.quote && classifyQuoteKind(attempt.quote.t ?? 0, at) !== 'stale') {
            entries.set(key, { quote: attempt.quote, fetchedAt: at });
            failureMarks.delete(key);
            evictEntryOverflow();
            return { ...attempt, fetchedAt: at, saturated: false };
        }
        if (attempt.fetchFailed) {
            const prev = failureMarks.get(key);
            const failures = Math.min((prev?.failures ?? 0) + 1, 32);
            const waitMs =
                attempt.retryAfterSeconds !== null
                    ? attempt.retryAfterSeconds * 1000
                    : Math.min(backoffBaseMs * 2 ** (failures - 1), backoffCapMs);
            failureMarks.set(key, { notBefore: at + waitMs, failures });
            evictMarkOverflow();
        }
        // null saneado sin fetchFailed (dato viejo/ausente): ni valor ni
        // marca — la próxima llamada lo reintenta enseguida.
        return { ...attempt, fetchedAt: attempt.quote ? at : null, saturated: false };
    };

    return {
        getQuote(symbol, fetcher) {
            const key = String(symbol).trim().toUpperCase();
            if (key.length === 0) {
                throw new TypeError('quote-cache: símbolo vacío tras normalizar');
            }
            const t0 = now();
            const hit = entries.get(key);
            // Revalidación con el reloj ACTUAL: TTL y frescura de sesión.
            if (hit && t0 - hit.fetchedAt <= ttlMs && hit.quote.t !== null && classifyQuoteKind(hit.quote.t, t0) !== 'stale') {
                return Promise.resolve({ quote: hit.quote, fetchFailed: false, retryAfterSeconds: null, fetchedAt: hit.fetchedAt, saturated: false });
            }
            if (hit) entries.delete(key);

            // Anti-estampida tras fallo: Retry-After del proveedor o backoff.
            const mark = failureMarks.get(key);
            if (mark && t0 < mark.notBefore) {
                return Promise.resolve({
                    quote: null,
                    fetchFailed: true,
                    retryAfterSeconds: Math.ceil((mark.notBefore - t0) / 1000),
                    fetchedAt: null,
                    saturated: false,
                });
            }

            // Dedupe: un fetch en curso por símbolo, compartido.
            const shared = inflight.get(key);
            if (shared) return shared.promise;

            // Saturación REAL: cuentan las operaciones sin asentar, no el
            // Map (un zombi tras timeout sigue ocupando su slot).
            if (activeOps >= maxInflight) {
                return Promise.resolve({ quote: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: true });
            }

            const token = {};
            const controller = new AbortController();
            activeOps += 1;
            const promise = new Promise<CachedQuote>((resolve) => {
                let settled = false;
                const releaseShare = () => {
                    const cur = inflight.get(key);
                    if (cur && cur.token === token) inflight.delete(key);
                };
                const finish = (attempt: QuoteFetchAttempt) => {
                    if (settled) return; // respuesta tardía tras timeout: se ignora, no se cachea
                    settled = true;
                    clearTimeout(timer);
                    releaseShare();
                    resolve(settle(key, attempt, now()));
                };
                const failQuietly: QuoteFetchAttempt = { quote: null, fetchFailed: true, retryAfterSeconds: null };
                const timer: ReturnType<typeof setTimeout> = setTimeout(() => {
                    controller.abort(); // la señal llega al fetch real si el fetcher la propaga
                    finish(failQuietly); // libera al llamador; el SLOT sigue ocupado hasta asentar
                }, fetchTimeoutMs);
                (timer as { unref?: () => void }).unref?.();
                Promise.resolve()
                    .then(() => fetcher(key, controller.signal))
                    .then(
                        (attempt) => finish(attempt ?? failQuietly),
                        () => finish(failQuietly), // rechazo del fetcher: mismo camino de fallo, sin excepción al llamador
                    )
                    .finally(() => {
                        activeOps -= 1; // el slot se libera SOLO al asentar de verdad
                        if (settled) releaseShare(); // zombi: limpieza defensiva
                    });
            });
            inflight.set(key, { promise, token });
            return promise;
        },
        size: () => entries.size,
        inflightSize: () => activeOps,
        failureSize: () => failureMarks.size,
    };
}
