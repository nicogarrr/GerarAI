'use server';

import { z } from 'zod';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import type { WatchlistNew13fItem } from '@/lib/watchlist/new-13f';

const holder = z.object({ cik: z.string(), name: z.string().nullable(), shares: z.number().nonnegative(), value_usd: z.number().nonnegative().nullable() });
const payload = z.object({ items: z.array(z.object({
    ticker: z.string(), status: z.string(), period: z.string().nullish(),
    new_positions: z.object({
        status: z.enum(['ok', 'valor_parcial', 'sin_detalle', 'sin_datos']),
        count: z.number().int().nonnegative().nullable(),
        value_known_count: z.number().int().nonnegative().nullable(),
        top_by_shares: z.array(holder), top_by_value: z.array(holder),
    }).nullish(),
})) });

/** Nuevas posiciones 13F de cada empresa de la watchlist del usuario.
    `unavailable` distingue un fallo del servicio de una lista realmente vacía. */
export async function getWatchlistNew13f(): Promise<{ data: WatchlistNew13fItem[] | null; unavailable: boolean }> {
    try {
        await requireAuthenticatedUser();
        const data = await researchRequest<{ items: WatchlistNew13fItem[] }>('/api/watchlist/new-13f');
        if (!payload.safeParse(data).success) return { data: null, unavailable: true };
        return { data: data.items, unavailable: false };
    } catch (error) {
        console.error('getWatchlistNew13f error:', error);
        return { data: null, unavailable: true };
    }
}
