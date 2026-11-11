'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import {
    LIVE_QUOTE_GROUPS,
    hasLiveQuotes,
    parseYahooQuote,
    yahooChartRequest,
    type LiveMarketsResult,
    type LiveQuote,
    type LiveQuoteSpec,
    type YahooChartMeta,
} from '@/lib/market/live-quotes';

const PER_SYMBOL_TIMEOUT_MS = 8_000;
const CONCURRENCY = 6;
/** Bajo el segundo de cache del panel (60s) para que un poll no reciba lo mismo. */
const CACHE_TTL_SECONDS = 55;

async function fetchOne(spec: LiveQuoteSpec): Promise<LiveQuote | null> {
    try {
        const { url, init } = yahooChartRequest(spec.symbol);
        const resp = await fetch(url, { ...init, signal: AbortSignal.timeout(PER_SYMBOL_TIMEOUT_MS), cache: 'no-store' });
        if (!resp.ok) return null;
        const payload = await resp.json();
        const result = payload?.chart?.result?.[0];
        const meta = result?.meta as YahooChartMeta | undefined;
        // Barras diarias del MISMO response: el cierre de referencia sale de
        // ellas (por dia/sesion en la tz del mercado), no del meta.
        const bars = {
            timestamps: result?.timestamp as (number | null)[] | undefined,
            closes: result?.indicators?.quote?.[0]?.close as (number | null)[] | undefined,
        };
        return parseYahooQuote(spec, meta ?? null, bars);
    } catch {
        return null;
    }
}

async function fetchAll(): Promise<LiveMarketsResult> {
    const specs = LIVE_QUOTE_GROUPS.flatMap((group) => group.specs.map((spec) => ({ group: group.key, spec })));
    const results = new Map<string, LiveQuote | null>();
    // Reuse each slot as soon as its symbol settles. Fixed waves leave up
    // to five slots idle behind one slow response in every wave.
    let next = 0;
    const worker = async () => {
        while (next < specs.length) {
            const { spec } = specs[next++];
            results.set(spec.symbol, await fetchOne(spec));
        }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, specs.length) }, worker));
    const snapshot: LiveMarketsResult = {
        fetchedAt: Date.now(),
        groups: LIVE_QUOTE_GROUPS.map((group) => ({
            key: group.key,
            quotes: group.specs.map((spec) => results.get(spec.symbol) ?? null),
        })),
    };
    // Reject inside the cache fetcher: outages must not be cached as a fresh
    // successful snapshot. Partial failures still return per-row nulls.
    if (!hasLiveQuotes(snapshot)) throw new Error('live_quotes_unavailable');
    return snapshot;
}

/**
 * Cotizaciones del panel /mercados, directas de Yahoo (sin pasar por el
 * backend de la VM). Un simbolo caido no tumba los demas: llega null y la
 * UI pinta N/D solo en su fila.
 */
export async function getLiveMarkets(): Promise<LiveMarketsResult> {
    await requireAuthenticatedUser();
    return cachedFetch('live-markets:v2', fetchAll, CACHE_TTL_SECONDS);
}
