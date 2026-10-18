'use server';

import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { requestCache } from '@/lib/cache/requestCache';
import { classifyError, getFriendlyErrorMessage, type ErrorCause } from '@/lib/types/errors';
import { getStockQuote, getStockFinancialDataLight } from '@/lib/actions/finnhub.actions';
import { getResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { sessionDateEt } from '@/lib/market/quote-freshness';

// Helper para obtener userId (researchRequest añade la identidad firmada
// vía researchIdentityHeaders usando el usuario autenticado).
async function getUserId(): Promise<string> {
    return (await requireAuthenticatedUser()).id;
}

/** Resultado de una mutación de watchlist (serializable a cliente). */
export interface WatchlistMutationResult {
    success: boolean;
    /** Causa del fallo para decidir el toast (offline → Reintentar, duplicate...) */
    code?: ErrorCause;
    message?: string;
}

function failure(error: unknown): WatchlistMutationResult {
    return {
        success: false,
        code: classifyError(error),
        message: getFriendlyErrorMessage(error, { duplicateMessage: 'Ya sigues este ticker.' }),
    };
}

/** Entrada devuelta por GET /api/watchlist del backend research. */
interface WatchlistEntry {
    symbol: string;
    company?: string | null;
    created_at?: string;
}

// Obtener watchlist del usuario actual desde el backend research (/api/watchlist).
// `unavailable` distingue un fallo del backend de una watchlist realmente vacía (F386).
export async function getWatchlistState(): Promise<{
    items: { symbol: string; addedAt: Date }[];
    unavailable: boolean;
}> {
    try {
        const userId = await getUserId();
        const items = await cachedFetch(
            `watchlist:${userId}`,
            () => researchRequest<WatchlistEntry[]>('/api/watchlist'),
            15,
        );
        if (!Array.isArray(items)) return { items: [], unavailable: true };
        return {
            items: items.map((item) => ({
                symbol: item.symbol,
                addedAt: item.created_at ? new Date(item.created_at) : new Date()
            })),
            unavailable: false,
        };
    } catch (error) {
        console.error('getWatchlist error:', error);
        return { items: [], unavailable: true };
    }
}

// Compatibilidad: los consumidores secundarios degradan a lista vacía sin romper.
export async function getWatchlist(): Promise<{ symbol: string; addedAt: Date }[]> {
    return (await getWatchlistState()).items;
}

// Añadir a watchlist
export async function addToWatchlist(symbol: string, company?: string): Promise<WatchlistMutationResult> {
    try {
        const userId = await getUserId();
        await researchRequest('/api/watchlist', {
            method: 'POST',
            body: jsonBody({
                symbol: symbol.toUpperCase(),
                ...(company ? { company } : {})
            })
        });
        requestCache.invalidate(`watchlist:${userId}`);
        revalidatePath('/watchlist');
        return { success: true };
    } catch (error) {
        console.error('addToWatchlist error:', error);
        return failure(error);
    }
}

// Eliminar de watchlist
export async function removeFromWatchlist(symbol: string): Promise<WatchlistMutationResult> {
    try {
        const userId = await getUserId();
        await researchRequest(`/api/watchlist/${encodeURIComponent(symbol)}`, {
            method: 'DELETE'
        });
        requestCache.invalidate(`watchlist:${userId}`);
        revalidatePath('/watchlist');
        return { success: true };
    } catch (error) {
        console.error('removeFromWatchlist error:', error);
        return failure(error);
    }
}
/**
 * Datos de mercado de una entrada de watchlist, resueltos por el LISTADO
 * REAL (master), nunca por el ticker desnudo.
 *
 * Antes la watchlist pedía Finnhub con el ticker pelado: para un emisor
 * no-US Finnhub free devuelve el gemelo americano — el ADR en USD del mismo
 * emisor (ASML salía a 1.743,94 US$ mientras su ficha research muestra la
 * línea de Amsterdam a 1.522,60 €, F253) u OTRO emisor (ALM -> Almonty) — y
 * la página lo formateaba siempre como USD. Además AENA salía «sin datos»
 * pese a tener cotización (Finnhub free no cubre BME; la ruta con sufijo
 * .MC sí, F254).
 *
 * Regla: el símbolo de cotización lo decide `quoteSymbolFor` con la bolsa y
 * divisa del master; sin correspondencia validada, «sin datos» honesto.
 * Perfil/métricas Finnhub SOLO para líneas US (quoteSymbol === ticker): en
 * un listado no-US serían del ADR o de un homónimo.
 */
export type WatchlistEntryData = {
    symbol: string;
    name: string;
    exchange: string | null;
    currency: string | null;
    price: number | null;
    change: number | null;
    changePercent: number | null;
    marketCap: number | null;
    peRatio: number | null;
    // F358: frescura del precio: 'live' = sesión en curso; 'close' = último
    // cierre fechado (con fecha en priceAsOf si se conoce). Un cierre NUNCA
    // se pinta como cotización actual.
    priceKind: 'live' | 'close' | null;
    priceAsOf: string | null;
    /** true = cotiza fuera de EE. UU.: capitalización y PER no se piden a Finnhub (serían del ADR u homónimo). */
    metricsNotApplicable: boolean;
};

export async function getWatchlistEntryData(symbol: string): Promise<WatchlistEntryData> {
    const normalized = symbol.trim().toUpperCase();
    const basics = await getResearchCompanyBasics(normalized);
    const quoteSymbol = quoteSymbolFor(basics, normalized);
    const base: WatchlistEntryData = {
        symbol: normalized,
        name: basics?.name || normalized,
        exchange: basics?.exchange || null,
        currency: basics?.currency || null,
        price: null,
        change: null,
        changePercent: null,
        marketCap: null,
        peRatio: null,
        priceKind: null,
        priceAsOf: null,
        metricsNotApplicable: false,
    };
    if (!quoteSymbol) return base;

    const usListing = quoteSymbol === normalized;
    base.metricsNotApplicable = !usListing;
    const [quote, light] = await Promise.all([
        getStockQuote(quoteSymbol),
        // La línea US es el listado real: sus métricas Finnhub son de ESTE
        // emisor. Para no-US ni se piden (ADR u homónimo).
        usListing ? getStockFinancialDataLight(normalized) : Promise.resolve(null),
    ]);

    // F358: la cotización llega con frescura validada en origen; solo se
    // muestra precio si hay kind ('live' o 'close' etiquetado), nunca stale.
    const price =
        quote && typeof quote.c === 'number' && Number.isFinite(quote.c) && quote.c > 0
            ? quote.c
            : null;
    const priceKind = price !== null ? quote?.kind ?? null : null;
    const priceAsOf = priceKind === 'close' && quote?.t ? sessionDateEt(quote.t) : null;
    const metrics = light?.metrics?.metric ?? {};
    const marketCapM = typeof metrics.marketCapitalization === 'number' ? metrics.marketCapitalization : null;
    const peRatio = typeof metrics.peTTM === 'number' && Number.isFinite(metrics.peTTM) ? metrics.peTTM : null;

    return {
        ...base,
        name: basics?.name || light?.profile?.name || normalized,
        // La divisa visible la pone SOLO el master (curado): ni la del
        // proveedor (puede ser discordante, F163) ni un «USD» asumido por
        // ser línea US — sin divisa real, número pelado.
        currency: base.currency,
        price,
        change:
            price === null
                ? null
                : typeof quote?.d === 'number' && Number.isFinite(quote.d)
                  ? quote.d
                  : null,
        changePercent:
            price === null
                ? null
                : typeof quote?.dp === 'number' && Number.isFinite(quote.dp)
                  ? quote.dp
                  : null,
        marketCap: marketCapM !== null ? marketCapM * 1e6 : null, // Finnhub devuelve M USD
        peRatio,
        priceKind,
        priceAsOf,
        metricsNotApplicable: !usListing,
    };
}
