'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { env } from '@/lib/env';
import { fetchJSON } from '@/lib/upstream/finnhub';
import type { FinnhubMetricsAll } from '@/lib/actions/finnhub.actions';

/** PER needs only the listing's metric response, never quote/profile/targets. */
export async function getStockPerMetric(symbol: string): Promise<FinnhubMetricsAll | null> {
    await requireAuthenticatedUser();
    if (!env.FINNHUB_API_KEY) return null;
    try {
        return await fetchJSON<FinnhubMetricsAll>(
            `https://finnhub.io/api/v1/stock/metric?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}&metric=all&token=${env.FINNHUB_API_KEY}`,
            86400,
        );
    } catch {
        return null;
    }
}
