'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { BACKEND_PAGE_SIZE, fetchAllBackendPages, type PaginatedBackendResponse } from '@/lib/paginated-backend';
import { researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { getWatchlistState } from '@/lib/actions/watchlist.actions';
import { openPositionTickers } from '@/lib/ticker-badges';

export type TickerContext = {
    portfolioTickers: string[];
    watchlistTickers: string[];
    /**
     * Qué lecturas respondieron bien. Un fallo NO equivale a «el usuario no
     * sigue empresas»: los consumidores que deciden a partir del contexto
     * (p. ej. el carril «Para ti» de noticias) deben distinguir ambos casos.
     */
    availability: { portfolio: boolean; watchlist: boolean };
};

/**
 * Tickers presentes en la cartera y en la watchlist del usuario, para los
 * badges «En cartera / En watchlist» (quick win UX 5). Degradación honesta:
 * si una lectura falla, su conjunto queda vacío — ningún badge es nunca una
 * afirmación falsa de pertenencia — y `availability` registra el fallo para
 * que nadie confunda «falló la lectura» con «el usuario no sigue empresas».
 */
export async function getTickerContext(): Promise<TickerContext> {
    const userId = (await requireAuthenticatedUser()).id;
    const [positionsResult, watchlistState] = await Promise.all([
        cachedFetch(
            `portfolio:${userId}:positions`,
            // Lectura completa: paginado page/page_size hasta agotar (fetchAllBackendPages lanza si no avanza).
            () => fetchAllBackendPages((page) => researchRequest<PaginatedBackendResponse<{ ticker: string; quantity: number | null }>>(`/api/portfolio/positions?page=${page}&page_size=${BACKEND_PAGE_SIZE}`, { fast: true }), (position) => position.ticker),
            15,
        ).then(
            (value) => ({ ok: true as const, value }),
            () => ({ ok: false as const, value: [] as Array<{ ticker: string; quantity: number | null }> }),
        ),
        // La watchlist NO se mide por excepción: getWatchlistState captura los
        // fallos y su `unavailable` es la fuente verdadera (el wrapper
        // getWatchlist() aplana el fallo a [] y lo haría invisible aquí).
        getWatchlistState(),
    ]);
    return {
        portfolioTickers: openPositionTickers(positionsResult.value),
        watchlistTickers: watchlistState.items.map((item) => item.symbol.toUpperCase()),
        availability: {
            portfolio: positionsResult.ok,
            watchlist: !watchlistState.unavailable,
        },
    };
}
