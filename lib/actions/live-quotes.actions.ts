'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import {
    LIVE_QUOTE_GROUPS,
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
        const meta = payload?.chart?.result?.[0]?.meta as YahooChartMeta | undefined;
        return parseYahooQuote(spec, meta ?? null);
    } catch {
        return null;
    }
}

async function fetchAll(): Promise<LiveMarketsResult> {
    const specs = LIVE_QUOTE_GROUPS.flatMap((group) => group.specs.map((spec) => ({ group: group.key, spec })));
    const results = new Map<string, LiveQuote | null>();
    for (let i = 0; i < specs.length; i += CONCURRENCY) {
        const batch = specs.slice(i, i + CONCURRENCY);
        const quotes = await Promise.all(batch.map(({ spec }) => fetchOne(spec)));
        batch.forEach(({ spec }, j) => results.set(spec.symbol, quotes[j]));
    }
    return {
        fetchedAt: Date.now(),
        groups: LIVE_QUOTE_GROUPS.map((group) => ({
            key: group.key,
            quotes: group.specs.map((spec) => results.get(spec.symbol) ?? null),
        })),
    };
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
