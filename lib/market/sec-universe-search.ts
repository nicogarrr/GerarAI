/**
 * Respaldo de ÚLTIMA instancia del buscador: el registro oficial de emisores
 * de la SEC (company_tickers_exchange.json, ~10k empresas con ticker en
 * mercados de EE. UU., gratis, sin clave ni cuota).
 *
 * Caso real 2026-11-19: «Antrophic» (errata) no devolvía nada ni en el
 * master ni en Finnhub el MISMO día de la IPO de Anthropic, y la app solo
 * ofrecía «Abrir la ficha de ANTROPHIC», una ficha vacía. Con este universo
 * la errata sugiere «Anthropic, PBC (ANT)» con fuente oficial; no se
 * inventa ni ticker ni fecha.
 *
 * Solo se consulta cuando local + master + proveedor no han devuelto NADA,
 * así nunca desplaza resultados de fuentes con más cobertura. La política
 * de erratas (≥ 5 letras; distancia 1 hasta 7, 2 desde 8, con transposición
 * de vecinas) es la misma que en data-engine (app/services/company_names.py):
 * una sola definición de «errata pequeña» en toda la app.
 */
import { SUPPORT_EMAIL } from '@/lib/config/brand';
import { exchangeDisplayName } from '@/lib/exchangeName';
import { foldSearchQuery } from '@/lib/search-query';

const SEC_TICKERS_URL = 'https://www.sec.gov/files/company_tickers_exchange.json';
const CACHE_TTL_MS = 24 * 3600 * 1000;
const FAILURE_RETRY_MS = 5 * 60 * 1000;
const FETCH_TIMEOUT_MS = 4000;
const MAX_SUGGESTIONS = 3;
const MIN_KEY_LENGTH = 5;

// Espejo de _GENERIC_FIRST_WORDS (data-engine/app/services/company_names.py):
// primeras palabras demasiado genéricas para identificar una empresa solas.
const GENERIC_FIRST_WORDS = new Set([
    'grupo', 'group', 'banco', 'bank', 'first', 'american', 'general', 'international', 'global',
    'united', 'national', 'new', 'china', 'the', 'royal', 'compania', 'company', 'pool', 'block',
    'target', 'meta', 'visa', 'booking', 'match', 'service', 'energy', 'capital', 'health',
]);

export type SecUniverseRow = { ticker: string; name: string; exchange: string | null };

type SecTickersFile = { fields?: unknown; data?: unknown };

let cache: { at: number; rows: SecUniverseRow[] } | null = null;
let lastFailureAt = 0;

/** Solo tests: vacía la caché del universo y el backoff de fallos. */
export function resetSecUniverseCacheForTests(): void {
    cache = null;
    lastFailureAt = 0;
}

/** Distancia de edición con transposición de vecinas (OSA), cortada en limit + 1.
 *  Espejo de _osa_distance (data-engine/app/services/company_names.py). */
export function osaDistance(a: string, b: string, limit: number): number {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    let prev2: number[] = [];
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
        const cur: number[] = [i, ...new Array<number>(b.length).fill(0)];
        for (let j = 1; j <= b.length; j++) {
            const cost = a[i - 1] === b[j - 1] ? 0 : 1;
            cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
            if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
                cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
            }
        }
        if (Math.min(...cur) > limit) return limit + 1;
        prev2 = prev;
        prev = cur;
    }
    return prev[b.length];
}

function words(text: string): string[] {
    return foldSearchQuery(text).toLowerCase().match(/[a-z0-9&]+/g) ?? [];
}

/** Claves de errata: primera palabra y nombre pegado (como company_names). */
function nameKeys(name: string): string[] {
    let parts = words(name);
    if (parts[0] === 'the' && parts.length >= 2) parts = parts.slice(1);
    if (!parts.length) return [];
    const keys = [parts[0]];
    if (parts.length >= 2) keys.push(parts.join(''));
    return keys.filter((key) => key.length >= MIN_KEY_LENGTH && !GENERIC_FIRST_WORDS.has(key) && /^[a-z]+$/.test(key));
}

function queryKeys(query: string): string[] {
    let parts = words(query);
    if (parts[0] === 'the' && parts.length >= 2) parts = parts.slice(1);
    if (!parts.length) return [];
    const keys = [parts[0]];
    if (parts.length >= 2) keys.push(parts.join(''));
    return keys.filter((key) => key.length >= MIN_KEY_LENGTH && /^[a-z]+$/.test(key));
}

function parseRows(payload: SecTickersFile): SecUniverseRow[] {
    const fields = Array.isArray(payload?.fields) ? payload.fields : [];
    const iName = fields.indexOf('name');
    const iTicker = fields.indexOf('ticker');
    const iExchange = fields.indexOf('exchange');
    if (iName < 0 || iTicker < 0 || !Array.isArray(payload?.data)) return [];
    const rows: SecUniverseRow[] = [];
    for (const raw of payload.data as unknown[]) {
        if (!Array.isArray(raw)) continue;
        const name = raw[iName];
        const ticker = raw[iTicker];
        if (typeof name !== 'string' || typeof ticker !== 'string' || !name || !ticker) continue;
        const exchange = iExchange >= 0 && typeof raw[iExchange] === 'string' ? raw[iExchange] as string : null;
        rows.push({ ticker, name, exchange });
    }
    return rows;
}

async function loadUniverse(): Promise<SecUniverseRow[]> {
    const now = Date.now();
    if (cache && now - cache.at < CACHE_TTL_MS) return cache.rows;
    // El backoff tras un fallo manda también con copia caducada: sin esto,
    // pasadas las 24 h y con sec.gov caído, cada búsqueda reintentaba la
    // descarga al momento (medido por el Auditor 2026-11-19).
    if (now - lastFailureAt < FAILURE_RETRY_MS) return cache?.rows ?? [];
    try {
        const response = await fetch(SEC_TICKERS_URL, {
            headers: { 'User-Agent': `GerarAI (${SUPPORT_EMAIL})` },
            signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        });
        if (!response.ok) throw new Error(`SEC tickers HTTP ${response.status}`);
        const rows = parseRows(await response.json() as SecTickersFile);
        cache = { at: now, rows };
        return rows;
    } catch {
        lastFailureAt = now;
        // Stale-while-error: el registro cambia poco a poco; la última copia
        // buena es mejor que ninguna sugerencia, y nunca sustituye a las
        // fuentes principales (esto solo corre cuando todas fallan en vacío).
        return cache?.rows ?? [];
    }
}

/** Candidatas del registro SEC para una consulta con errata, ordenadas por
 *  distancia y ticker. Vacío si no hay candidata clara: nunca se inventa. */
export function rankSecRows(query: string, rows: SecUniverseRow[], max = MAX_SUGGESTIONS): SecUniverseRow[] {
    const qKeys = queryKeys(query);
    if (!qKeys.length) return [];
    const scored: Array<{ distance: number; row: SecUniverseRow }> = [];
    for (const row of rows) {
        const keys = nameKeys(row.name);
        let best: number | null = null;
        for (const qKey of qKeys) {
            const limit = qKey.length <= 7 ? 1 : 2;
            for (const key of keys) {
                const distance = osaDistance(qKey, key, limit);
                if (distance <= limit && (best === null || distance < best)) best = distance;
            }
        }
        if (best !== null) scored.push({ distance: best, row });
    }
    scored.sort((a, b) => a.distance - b.distance || a.row.ticker.localeCompare(b.row.ticker));
    return scored.slice(0, max).map((entry) => entry.row);
}

/** Sugerencias del registro oficial SEC para el buscador, con el formato de
 *  cualquier otro resultado. La bolsa viene del propio fichero de la SEC
 *  (puede faltar en emisores muy nuevos: entonces «US», sin adornar). */
export async function searchSecUniverse(query: string): Promise<StockWithWatchlistStatus[]> {
    if (!queryKeys(query).length) return [];
    const matches = rankSecRows(query, await loadUniverse());
    return matches.map((row) => ({
        symbol: row.ticker.toUpperCase(),
        name: row.name,
        exchange: exchangeDisplayName(row.exchange) ?? 'US',
        type: 'Stock',
        isInWatchlist: false,
    }));
}
