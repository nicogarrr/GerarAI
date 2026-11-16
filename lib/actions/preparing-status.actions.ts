'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

/** Only these small reads are polled. Never run a full research workspace. */
export async function getPreparingStatus(ticker: string, kind: 'dca' | 'news'): Promise<'preparing' | 'ready' | 'unavailable'> {
    if (!/^[A-Z0-9.\-=^]{1,24}$/.test(ticker) || !['dca', 'news'].includes(kind)) return 'unavailable';
    try {
        await requireAuthenticatedUser();
        const path = kind === 'news'
            ? `/api/watchlist/news-preparing/${encodeURIComponent(ticker)}`
            : `/api/watchlist/dca-signals/${encodeURIComponent(ticker)}/hit-rates`;
        const data = await researchRequest<{ preparing?: boolean; available?: boolean; rows?: unknown[] } | null>(path, { fast: true });
        if (!data) return 'unavailable';
        if (data.preparing === true) return 'preparing';
        // News status must explicitly say preparation finished. DCA returns its data instead.
        if (kind === 'news' && data.preparing !== false) return 'unavailable';
        if (kind === 'dca' && (typeof data.available !== 'boolean' || !Array.isArray(data.rows))) return 'unavailable';
        return 'ready';
    } catch {
        return 'unavailable';
    }
}
