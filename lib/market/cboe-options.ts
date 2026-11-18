/**
 * Cadena de opciones de CBOE (delayed quotes, endpoint público sin clave):
 * fuente OFICIAL y gratuita de primas de opciones US para valorar las
 * posiciones de opción de la cuenta demo manual.
 *
 * Por qué CBOE y no el subyacente ni Yahoo:
 * - La cotización del subyacente NO es la prima del contrato (regla de
 *   veracidad de la demo): valorar una opción con el precio de la acción
 *   sería inventar el dato.
 * - /v7/finance/options de Yahoo exige crumb y responde 429 con facilidad
 *   desde IPs de datacenter; CBOE publica su delayed quotes API sin auth
 *   (datos diferidos >= 15 min: la etiqueta de cada fila muestra la hora
 *   REAL de la última operación y la marca "diferida", nunca "en vivo").
 *
 * Reglas de honestidad (cubiertas por scripts/cboe-options.test.ts y
 * scripts/demo-valuation.test.ts):
 * - Precio de entrada ÚNICO: last_trade_price con su last_trade_time, tal
 *   cual lo publica CBOE. Un contrato sin operación registrada sale N/D:
 *   NO se inventa una prima a partir de bid/ask ni del teórico.
 * - Divisa: la delayed quotes API de CBOE cubre opciones US, que negocian
 *   en USD (propiedad de la fuente, no inferida del símbolo): solo se
 *   valoran posiciones de opción en USD; en otra divisa la fila es N/D.
 * - Contratos ajustados: el símbolo OCC ajustado no casa con el contrato
 *   fase 1 (multiplicador 100, sin ajuste) y simplemente no se encuentra
 *   en la cadena => N/D con motivo, nunca una prima aproximada.
 * - Caché: dedupe por subyacente, TTL 60 s, concurrencia acotada, backoff
 *   con Retry-After. La cadena es dato PÚBLICO de mercado (ningún dato de
 *   usuario entra en esta capa). fetchedAt REAL viaja al llamador para un
 *   asOf honesto bajo caché (min de lo servido, como en la valoración de
 *   acciones).
 *
 * Módulo cargable con node --experimental-strip-types: sin alias `@/`.
 */

/** Prima de un contrato tal como la publica CBOE (saneada). */
export type CboeOptionPremium = {
    /** Último precio negociado del contrato (prima por acción); null si nunca negoció. */
    lastTradePrice: number | null;
    /** Hora de la última operación "yyyy-mm-ddThh:mm:ss" (Nueva York, naive); null sin operación. */
    lastTradeTime: string | null;
};

export type CboeChain = ReadonlyMap<string, CboeOptionPremium>;

/** Clave canónica de contrato dentro de la cadena saneada. */
export function cboeContractKey(underlying: string, expiry: string, callPut: 'call' | 'put', strike: number): string {
    return `${underlying.toUpperCase()}|${expiry}|${callPut}|${Math.round(strike * 1000)}`;
}

/**
 * Símbolo OCC "ASTS261120C00045000" -> { underlying, expiry, callPut, strike }.
 * Raíz de 1-6 letras seguida de AAMMDD, C/P y strike*1000 en 8 dígitos.
 * null si no casa (raíz ajustada, formato desconocido): ese contrato NO se
 * valorará (mejor N/D que una prima del contrato equivocado).
 */
export function parseOccSymbol(symbol: unknown): { underlying: string; expiry: string; callPut: 'call' | 'put'; strike: number } | null {
    if (typeof symbol !== 'string') return null;
    const m = /^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol.trim().toUpperCase());
    if (!m) return null;
    const [, underlying, yy, mm, dd, cp, strikeRaw] = m;
    const year = 2000 + Number(yy);
    const month = Number(mm);
    const day = Number(dd);
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    // Fecha civil REAL (rechaza 31 de noviembre y similares): una fecha
    // imposible identificaría mal el contrato y valoraríamos con él.
    const probe = new Date(Date.UTC(year, month - 1, day));
    if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return null;
    const expiry = `20${yy}-${mm}-${dd}`;
    const strike = Number(strikeRaw) / 1000;
    if (!(strike >= 0) || !Number.isFinite(strike)) return null;
    return { underlying, expiry, callPut: cp === 'C' ? 'call' : 'put', strike };
}

const MAX_CHAIN_ROWS = 20_000;
const PRICE_MAX = 1_000_000;

function finiteOrNull(value: unknown, max: number): number | null {
    // Cadena vacía o solo espacios: Number('') === 0, y 0 no es una operación
    // (auditor 18-nov-2026: la fila salía valorada a 0 con PyG -100 % inventada).
    if (typeof value === 'string' && value.trim() === '') return null;
    const n = typeof value === 'string' ? Number(value) : value;
    if (typeof n !== 'number' || !Number.isFinite(n)) return null;
    if (n < 0 || n > max) return null;
    return n;
}

const TRADE_TIME_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(:(\d{2}))?$/;

/**
 * Hora de operación tal cual la publica CBOE (Nueva York, naive) si es una
 * fecha y hora que EXISTEN; null en cualquier otro caso. El regex solo fija
 * la forma: "2026-99-99T99:99:99" lo pasa y luego rompía el formateo de la
 * etiqueta con RangeError (auditor 18-nov-2026), así que aquí se valida el
 * valor: mes 1-12, día civil real (ni 30 de febrero), hora 0-23, minuto y
 * segundo 0-59.
 */
function validTradeTime(raw: unknown): string | null {
    if (typeof raw !== 'string') return null;
    const m = TRADE_TIME_RE.exec(raw);
    if (!m) return null;
    const [, yy, mm, dd, hh, mi, , ss] = m;
    const year = Number(yy);
    const month = Number(mm);
    const day = Number(dd);
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    if (Number(hh) > 23 || Number(mi) > 59 || (ss !== undefined && Number(ss) > 59)) return null;
    const probe = new Date(Date.UTC(year, month - 1, day));
    if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return null;
    return raw;
}

/**
 * Sanea el payload de la delayed quotes API de CBOE a un mapa
 * clave-canónica -> prima. Entradas no reconocibles se descartan (nunca se
 * valoran con datos a medias). Devuelve null si el payload no tiene la forma
 * esperada en absoluto (el llamador lo trata como fallo de la fuente).
 */
export function sanitizeCboeChain(payload: unknown): Map<string, CboeOptionPremium> | null {
    const options = (payload as { data?: { options?: unknown } })?.data?.options;
    if (!Array.isArray(options)) return null;
    const map = new Map<string, CboeOptionPremium>();
    for (const row of options.slice(0, MAX_CHAIN_ROWS)) {
        const parsed = parseOccSymbol((row as { option?: unknown })?.option);
        if (!parsed) continue;
        const lastTradeTime = validTradeTime((row as { last_trade_time?: unknown })?.last_trade_time);
        map.set(cboeContractKey(parsed.underlying, parsed.expiry, parsed.callPut, parsed.strike), {
            lastTradePrice: finiteOrNull((row as { last_trade_price?: unknown })?.last_trade_price, PRICE_MAX),
            lastTradeTime,
        });
    }
    return map;
}

/** Intento de cadena tal como lo produce el fetcher del llamador. */
export type CboeChainAttempt = {
    chain: Map<string, CboeOptionPremium> | null;
    fetchFailed: boolean;
    retryAfterSeconds: number | null;
};

export type CachedCboeChain = CboeChainAttempt & {
    /** Epoch ms en que la fuente entregó el dato (también si viene de caché). null sin cadena. */
    fetchedAt: number | null;
    /** true = saturación LOCAL de concurrencia (sin fetch); false en cualquier otro desenlace. */
    saturated: boolean;
};

export type CboeChainCacheOptions = {
    /** Vida máxima de una cadena cacheada. Defecto 60 s. */
    ttlMs?: number;
    /** Máximo de subyacentes cacheados; al superarlo se expulsa el más viejo. Defecto 100. */
    maxEntries?: number;
    /** Máximo de fetches en curso; al saturarse, resultado degradado sin fetch. Defecto 8 (cadenas pesadas). */
    maxInflight?: number;
    /** Timeout por fetch; al cumplirse cuenta como fallo y se ignora la respuesta tardía. Defecto 12 s. */
    fetchTimeoutMs?: number;
    /** Máximo de marcas anti-estampida; al superarlo se expulsa la que expira antes. Defecto 100. */
    maxFailureMarks?: number;
    /** Tope al Retry-After del proveedor que se respeta. Defecto 300 s. */
    maxRetryAfterSeconds?: number;
    /** Backoff propio sin Retry-After: base y tope. Defectos 1 s y 60 s. */
    failureBackoffBaseMs?: number;
    failureBackoffCapMs?: number;
    /** Reloj inyectable (fixtures). */
    now?: () => number;
};

type ChainFetcher = (underlying: string, signal: AbortSignal) => Promise<CboeChainAttempt>;

const DEFAULT_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

/**
 * Base de la delayed quotes API de CBOE (endpoint PÚBLICO, sin auth, dato
 * diferido >= 15 min). URL de proveedor EXTERNO, auditada en el censo de
 * scripts/raw-fetch-api-contract.test.ts: el path contiene "/api/" por
 * coincidencia de nombre de CBOE, nunca es una ruta interna. Se construye
 * fuera del fetch para que ese censo la trate como lo que es (externa).
 */
const CBOE_DELAYED_QUOTES_BASE = 'https://cdn.cboe.com/api/global/delayed_quotes';

/**
 * Descarga la cadena de un subyacente de la delayed quotes API de CBOE y la
 * sanea. fetchFailed distingue el fallo transitorio (HTTP no-OK, red,
 * timeout, payload irreconocible) del dato presente: NO hay "dato
 * genuinamente ausente" a nivel cadena — un subyacente sin opciones o no
 * cubierto llega como payload sin options o 404, y ambos se tratan como
 * fallo transitorio con backoff (el llamador deja la fila N/D con motivo).
 */
export async function fetchCboeChain(underlying: string, signal?: AbortSignal): Promise<CboeChainAttempt> {
    const symbol = underlying.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(symbol)) return { chain: null, fetchFailed: true, retryAfterSeconds: null };
    try {
        const response = await fetch(`${CBOE_DELAYED_QUOTES_BASE}/options/${encodeURIComponent(symbol)}.json`, {
            headers: { 'user-agent': DEFAULT_UA, accept: 'application/json' },
            cache: 'no-store',
            signal: signal ?? AbortSignal.timeout(12_000),
        });
        if (!response.ok) {
            const retryAfter = Number.parseInt(response.headers.get('retry-after') ?? '', 10);
            return { chain: null, fetchFailed: true, retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null };
        }
        const chain = sanitizeCboeChain(await response.json());
        if (!chain) return { chain: null, fetchFailed: true, retryAfterSeconds: null };
        return { chain, fetchFailed: false, retryAfterSeconds: null };
    } catch {
        return { chain: null, fetchFailed: true, retryAfterSeconds: null };
    }
}

type Entry = { chain: Map<string, CboeOptionPremium>; fetchedAt: number };
type FailureMark = { notBefore: number };

/**
 * Caché dedupe de cadenas de opciones PÚBLICAS con la misma disciplina que
 * lib/market/quote-cache.ts: dedupe de fetches concurrentes, concurrencia
 * acotada de verdad (saturación = resultado degradado inmediato sin fetch),
 * timeout por fetch, solo se cachean éxitos saneados, fallos con ventana de
 * reintento (Retry-After acotado o backoff exponencial acotado) y reloj
 * inyectable. Una cadena es ~0,5 MB: el TTL de 60 s y el tope de 8 fetches
 * en curso acotan ancho de banda y memoria por ráfaga.
 */
export function createCboeChainCache(options: CboeChainCacheOptions = {}) {
    const ttlMs = Number.isFinite(options.ttlMs) && (options.ttlMs as number) > 0 ? (options.ttlMs as number) : 60_000;
    const maxEntries = Number.isInteger(options.maxEntries) && (options.maxEntries as number) > 0 ? (options.maxEntries as number) : 100;
    const maxInflight = Number.isInteger(options.maxInflight) && (options.maxInflight as number) > 0 ? (options.maxInflight as number) : 8;
    const fetchTimeoutMs = Number.isFinite(options.fetchTimeoutMs) && (options.fetchTimeoutMs as number) > 0 ? (options.fetchTimeoutMs as number) : 12_000;
    const maxFailureMarks = Number.isInteger(options.maxFailureMarks) && (options.maxFailureMarks as number) > 0 ? (options.maxFailureMarks as number) : 100;
    const maxRetryAfterSeconds = Number.isFinite(options.maxRetryAfterSeconds) && (options.maxRetryAfterSeconds as number) > 0 ? (options.maxRetryAfterSeconds as number) : 300;
    const failureBackoffBaseMs = Number.isFinite(options.failureBackoffBaseMs) && (options.failureBackoffBaseMs as number) > 0 ? (options.failureBackoffBaseMs as number) : 1_000;
    const failureBackoffCapMs = Number.isFinite(options.failureBackoffCapMs) && (options.failureBackoffCapMs as number) > 0 ? (options.failureBackoffCapMs as number) : 60_000;
    const now = options.now ?? (() => Date.now());

    const entries = new Map<string, Entry>();
    const inflight = new Map<string, Promise<CachedCboeChain>>();
    const failures = new Map<string, FailureMark & { count: number }>();

    const rememberFailure = (key: string, retryAfterSeconds: number | null) => {
        if (failures.size >= maxFailureMarks && !failures.has(key)) {
            let oldestKey: string | null = null;
            let oldestNotBefore = Infinity;
            for (const [k, mark] of failures) {
                if (mark.notBefore < oldestNotBefore) {
                    oldestNotBefore = mark.notBefore;
                    oldestKey = k;
                }
            }
            if (oldestKey !== null) failures.delete(oldestKey);
        }
        const prev = failures.get(key);
        const count = Math.min((prev?.count ?? 0) + 1, 32);
        const waitMs =
            retryAfterSeconds !== null
                ? Math.min(retryAfterSeconds, maxRetryAfterSeconds) * 1000
                : Math.min(failureBackoffBaseMs * 2 ** (count - 1), failureBackoffCapMs);
        failures.set(key, { notBefore: now() + waitMs, count });
    };

    const getChain = async (underlying: string, fetcher: ChainFetcher = fetchCboeChain): Promise<CachedCboeChain> => {
        const key = underlying.trim().toUpperCase();
        const cached = entries.get(key);
        if (cached && now() - cached.fetchedAt <= ttlMs) {
            return { chain: cached.chain, fetchFailed: false, retryAfterSeconds: null, fetchedAt: cached.fetchedAt, saturated: false };
        }
        const mark = failures.get(key);
        if (mark && now() < mark.notBefore) {
            return { chain: null, fetchFailed: true, retryAfterSeconds: Math.ceil((mark.notBefore - now()) / 1000), fetchedAt: null, saturated: false };
        }
        const pending = inflight.get(key);
        if (pending) return pending;
        if (inflight.size >= maxInflight) {
            return { chain: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: true };
        }
        const promise = (async (): Promise<CachedCboeChain> => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), fetchTimeoutMs);
            try {
                const attempt = await fetcher(key, controller.signal);
                if (controller.signal.aborted) {
                    rememberFailure(key, null);
                    return { chain: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: false };
                }
                if (attempt.chain) {
                    const fetchedAt = now();
                    if (entries.size >= maxEntries && !entries.has(key)) {
                        let oldestKey: string | null = null;
                        let oldestAt = Infinity;
                        for (const [k, entry] of entries) {
                            if (entry.fetchedAt < oldestAt) {
                                oldestAt = entry.fetchedAt;
                                oldestKey = k;
                            }
                        }
                        if (oldestKey !== null) entries.delete(oldestKey);
                    }
                    entries.set(key, { chain: attempt.chain, fetchedAt });
                    failures.delete(key);
                    return { chain: attempt.chain, fetchFailed: false, retryAfterSeconds: null, fetchedAt, saturated: false };
                }
                if (attempt.fetchFailed) rememberFailure(key, attempt.retryAfterSeconds);
                return { chain: null, fetchFailed: attempt.fetchFailed, retryAfterSeconds: attempt.retryAfterSeconds, fetchedAt: null, saturated: false };
            } catch {
                rememberFailure(key, null);
                return { chain: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: false };
            } finally {
                clearTimeout(timer);
                inflight.delete(key);
            }
        })();
        inflight.set(key, promise);
        return promise;
    };

    return { getChain };
}
