'use server';

import type { TrackedAnalysisStatus } from '@/lib/tracked-analysis-status';
import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';
import { requestCache } from '@/lib/cache/requestCache';
import { classifyError, getFriendlyErrorMessage, type ErrorCause } from '@/lib/types/errors';
import { getStockQuote, getStockValuationBasics } from '@/lib/actions/finnhub.actions';
import { getResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { hasPriorClose } from '@/lib/market/session-change';
import { sessionDateEt } from '@/lib/market/quote-freshness';
import type { ExtendedQuote } from '@/lib/market/extended-quote';

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
    analysis?: TrackedAnalysisStatus | null;
    symbol: string;
    company?: string | null;
    created_at?: string;
}

// Obtener watchlist del usuario actual desde el backend research (/api/watchlist).
// `unavailable` distingue un fallo del backend de una watchlist realmente vacía (F386).
export async function getWatchlistState(): Promise<{
    items: { symbol: string; addedAt: Date; analysis?: TrackedAnalysisStatus | null }[];
    unavailable: boolean;
}> {
    try {
        await getUserId();
        // Membership is transactional user state. Process-local TTL cannot be
        // invalidated across Vercel instances after add/remove elsewhere.
        const items = await researchRequest<WatchlistEntry[]>('/api/watchlist');
        if (!Array.isArray(items)) return { items: [], unavailable: true };
        return {
            items: items.map((item) => ({
                symbol: item.symbol,
                analysis: item.analysis,
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
        revalidatePath(`/research/${encodeURIComponent(symbol.toUpperCase())}`);
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
        revalidatePath(`/research/${encodeURIComponent(symbol.toUpperCase())}`);
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
    /** True cuando el cap lo deriva el backend (precio x acciones): se marca «· derivado». */
    marketCapDerived: boolean;
    peRatio: number | null;
    /** 'ttm' = Finnhub peTTM (línea US); 'fy' = respaldo backend cierre/EPS diluido FY. */
    peKind: 'ttm' | 'fy' | null;
    /** Procedencia del PER visible: Finnhub (TTM, línea US) o la cadena del backend («PER: cierre … / eps_diluido FY…»). Null sin PER. */
    peSource: string | null;
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
        marketCapDerived: false,
        peRatio: null,
        peKind: null,
        peSource: null,
        priceKind: null,
        priceAsOf: null,
        metricsNotApplicable: false,
    };
    if (!quoteSymbol) return base;

    const usListing = quoteSymbol === normalized;
    base.metricsNotApplicable = !usListing;
    const [quote, light, backend] = await Promise.all([
        getStockQuote(quoteSymbol),
        // La línea US es el listado real: sus métricas Finnhub son de ESTE
        // emisor. Para no-US ni se piden (ADR u homónimo): se usa el
        // respaldo propio del backend research (cap proveedor o derivado
        // precio x acciones; PER = cierre / EPS diluido FY).
        // Solo metric + profile2 (getStockValuationBasics): la versión
        // completa pedía /quote duplicada y /price-target sin uso.
        usListing ? getStockValuationBasics(normalized) : Promise.resolve(null),
        !usListing
            ? researchRequest<{
                  market_cap: number | null;
                  per: number | null;
                  currency: string | null;
                  sources: string[];
              }>(
                  `/api/watchlist/metrics/${encodeURIComponent(normalized)}`,
              ).catch(() => null)
            : Promise.resolve(null),
    ]);

    // F358: la cotización llega con frescura validada en origen; solo se
    // muestra precio si hay kind ('live' o 'close' etiquetado), nunca stale.
    const price =
        quote && typeof quote.c === 'number' && Number.isFinite(quote.c) && quote.c > 0
            ? quote.c
            : null;
    const priceKind = price !== null ? quote?.kind ?? null : null;
    const priceAsOf = priceKind === 'close'
        ? quote?.closeDate ?? (quote?.t ? sessionDateEt(quote.t) : null)
        : null;
    const metrics = light?.metrics?.metric ?? {};
    const marketCapM = typeof metrics.marketCapitalization === 'number' ? metrics.marketCapitalization : null;
    const peRatio = typeof metrics.peTTM === 'number' && Number.isFinite(metrics.peTTM) ? metrics.peTTM : null;
    const backendCap = backend && typeof backend.market_cap === 'number' ? backend.market_cap : null;
    const backendPer = backend && typeof backend.per === 'number' && Number.isFinite(backend.per) ? backend.per : null;
    const backendDerived = (backend?.sources ?? []).some((src) => src.toLowerCase().includes('derivada'));
    const backendPerSource = (backend?.sources ?? []).find((src) => src.startsWith('PER:')) ?? null;

    return {
        ...base,
        name: basics?.name || light?.profile?.name || normalized,
        // La divisa visible la pone SOLO el master (curado): ni la del
        // proveedor (puede ser discordante, F163) ni un «USD» asumido por
        // ser línea US — sin divisa real, número pelado.
        // Master curado manda; para no-US el backend devuelve la divisa real
        // de la compañía y la rellena cuando el master no la conoce.
        currency: base.currency ?? backend?.currency ?? null,
        price,
        change:
            price === null || !hasPriorClose(quote)
                ? null
                : typeof quote?.d === 'number' && Number.isFinite(quote.d)
                  ? quote.d
                  : null,
        changePercent:
            price === null || !hasPriorClose(quote)
                ? null
                : typeof quote?.dp === 'number' && Number.isFinite(quote.dp)
                  ? quote.dp
                  : null,
        marketCap: marketCapM !== null
            ? marketCapM * 1e6 // Finnhub devuelve M USD
            : backendCap,
        marketCapDerived: marketCapM === null && backendCap !== null && backendDerived,
        peRatio: peRatio ?? backendPer,
        peKind: peRatio !== null ? 'ttm' : backendPer !== null ? 'fy' : null,
        // Trazabilidad del número: sin fuente visible un PER erróneo (QA
        // 2026-10-19: AENA 2,0x por EPS FY mal cargado) parece dato oficial.
        peSource: peRatio !== null ? 'PER TTM (Finnhub)' : backendPerSource,
        priceKind,
        priceAsOf,
        metricsNotApplicable: !usListing,
    };
}

// ---- Monitor denso (F: watchlist monitor) ----
// Datos propios/trazables del backend research: minimo 52 semanas desde
// market_prices, proximo resultado via NASDAQ publico (mismo conector que
// /api/calendar/earnings) y comparacion con la ultima tesis publicada.
// Cualquier pieza sin dato llega a null: la UI pinta N/D, nunca inventa.
export type WatchlistMonitorItem = {
    low_52w: number | null;
    low_52w_date: string | null;
    low_52w_sessions: number;
    last_close: number | null;
    last_close_date: string | null;
    fair_value: number | null;
    fair_value_thesis_version: number | null;
    valuation_side: 'infravalorada' | 'sobrevalorada' | null;
    currency: string | null;
    next_earnings_date: string | null;
    next_earnings_source: string | null;
};

export async function getWatchlistMonitor(
    symbols: string[],
): Promise<{ items: Record<string, WatchlistMonitorItem>; earningsStatus: string }> {
    const wanted = symbols.map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (wanted.length === 0) return { items: {}, earningsStatus: 'skipped' };
    try {
        const data = await researchRequest<{
            items: Record<string, WatchlistMonitorItem>;
            earnings_status: string;
        }>(`/api/watchlist/monitor?tickers=${encodeURIComponent(wanted.join(','))}`);
        return { items: data?.items ?? {}, earningsStatus: data?.earnings_status ?? 'unavailable' };
    } catch {
        return { items: {}, earningsStatus: 'unavailable' };
    }
}

// Pre/post-mercado (Yahoo via backend propio, cache 60s por ticker).
export async function getExtendedQuote(symbol: string): Promise<ExtendedQuote | null> {
    try {
        return await researchRequest<ExtendedQuote>(
            `/api/companies/${encodeURIComponent(symbol.trim().toUpperCase())}/extended-quote`,
        );
    } catch {
        return null;
    }
}
