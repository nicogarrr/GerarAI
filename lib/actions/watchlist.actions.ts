'use server';

import { requestLocale } from '@/lib/research/backend-error-locale';
import type { TrackedAnalysisStatus } from '@/lib/tracked-analysis-status';
import type { components } from '@/lib/research/openapi.generated';
import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest, jsonBody } from '@/lib/research/client';
import { requestCache } from '@/lib/cache/requestCache';
import { AppError, classifyError, getFriendlyErrorMessage, type ErrorCause } from '@/lib/types/errors';
import { getStockQuote, getStockValuationBasics } from '@/lib/actions/finnhub.actions';
import { getResearchCompanyBasics, type ResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { emptyWatchlistEntry } from '@/lib/watchlist/entry-fallback';
import { isUsQuoteLine, quoteSymbolFor } from '@/lib/market/quote-symbol';
import { chartPriceUnit } from '@/lib/market/chart-price-units';
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

function failure(error: unknown, locale: 'es' | 'en' = 'es'): WatchlistMutationResult {
    return {
        success: false,
        code: classifyError(error),
        message: getFriendlyErrorMessage(error, { locale }),
    };
}

/** Entrada devuelta por GET /api/watchlist del backend research (tipo del OpenAPI generado). */
type WatchlistEntry = components['schemas']['WatchlistItemOut'];

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
        return failure(error, await requestLocale());
    }
}

/**
 * Alta desde el buscador de la propia /watchlist: el símbolo puede venir con
 * sufijo de mercado (SAN.MC de Finnhub) y la watchlist guarda el ticker
 * canónico del master (SAN). El POST del backend NO resuelve alias (guarda
 * el literal), así que la canonicalización se hace aquí vía research; si el
 * master no conoce el símbolo se usa el literal, como hasta ahora.
 */
export async function addToWatchlistCanonical(symbol: string, company?: string): Promise<WatchlistMutationResult> {
    const normalized = symbol.trim().toUpperCase();
    const basics = await getResearchCompanyBasics(normalized);
    const canonical = basics?.ticker?.trim().toUpperCase() || normalized;
    return addToWatchlist(canonical, company ?? basics?.name);
}

// Eliminar de watchlist
export async function removeFromWatchlist(symbol: string): Promise<WatchlistMutationResult> {
    try {
        const userId = await getUserId();
        try {
            await researchRequest(`/api/watchlist/${encodeURIComponent(symbol)}`, {
                method: 'DELETE'
            });
        } catch (error) {
            // Idempotente: 404 = ya no estaba (quitado en otra pestaña o
            // dispositivo). El objetivo del usuario ya se cumple; mostrar
            // «error + Reintentar» dejaba la fila vieja y un reintento que
            // siempre vuelve a fallar.
            if (!(error instanceof AppError && error.statusCode === 404)) throw error;
        }
        requestCache.invalidate(`watchlist:${userId}`);
        revalidatePath('/watchlist');
        revalidatePath(`/research/${encodeURIComponent(symbol.toUpperCase())}`);
        return { success: true };
    } catch (error) {
        console.error('removeFromWatchlist error:', error);
        return failure(error, await requestLocale());
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
    /** Etiqueta corta de la fuente del PER para mostrar junto al número («Finnhub» o la fuente del cálculo propio). Null sin PER. */
    peSourceLabel: string | null;
    // F358: frescura del precio: 'live' = sesión en curso; 'close' = último
    // cierre fechado (con fecha en priceAsOf si se conoce). Un cierre NUNCA
    // se pinta como cotización actual.
    priceKind: 'live' | 'close' | null;
    priceAsOf: string | null;
    /** true = cotiza fuera de EE. UU.: capitalización y PER no se piden a Finnhub (serían del ADR u homónimo). */
    metricsNotApplicable: boolean;
    /** Símbolo del listado real validado (p. ej. AENA.MC); null sin listado verificado. Lo usa la celda de objetivos de analistas. */
    quoteSymbol: string | null;
};

type BackendWatchlistMetrics = components['schemas']['WatchlistMetricsOut'];

function fetchBackendMetrics(symbol: string): Promise<BackendWatchlistMetrics | null> {
    return researchRequest<BackendWatchlistMetrics>(
        `/api/watchlist/metrics/${encodeURIComponent(symbol)}`,
    ).catch(() => null);
}

export async function getWatchlistEntryData(
    symbol: string,
    precomputedBasics?: ResearchCompanyBasics | null,
): Promise<WatchlistEntryData> {
    const normalized = symbol.trim().toUpperCase();
    // La página de watchlist resuelve el master en su propia oleada para
    // conservar nombre/divisa aunque la cotización agote su presupuesto;
    // el resto de consumidores (inicio) la leen aquí como siempre.
    const basics = precomputedBasics !== undefined ? precomputedBasics : await getResearchCompanyBasics(normalized);
    const quoteSymbol = quoteSymbolFor(basics, normalized);
    const base = emptyWatchlistEntry(normalized, basics, quoteSymbol);
    if (!quoteSymbol) return base;


    // Linea US derivada de bolsa/divisa, no de quoteSymbol === ticker (CGEO.L
    // cumple la igualdad y cotiza en GBX: sus metricas no son las de Finnhub).
    const usListing = isUsQuoteLine(basics, normalized);
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
            ? fetchBackendMetrics(normalized)
            : Promise.resolve(null),
    ]);

    // F358: la cotización llega con frescura validada en origen; solo se
    // muestra precio si hay kind ('live' o 'close' etiquetado), nunca stale.
    // Unidad de la cotización (Yahoo declara «GBp» en Londres: 118,25 p =
    // 1,1825 £). El precio se pasa a la unidad mayor antes de rotularlo con
    // la divisa del master (GBP); sin esto la fila decía «118,25 GBP» (×100).
    const quoteUnit = chartPriceUnit(quote?.currency ?? null);
    const masterUnit = chartPriceUnit(base.currency);
    const unitDivisor =
        quoteUnit && quoteUnit.divisor !== 1 && (!masterUnit || masterUnit.currency === quoteUnit.currency)
            ? quoteUnit.divisor
            : 1;
    const price =
        quote && typeof quote.c === 'number' && Number.isFinite(quote.c) && quote.c > 0
            ? quote.c / unitDivisor
            : null;
    const priceKind = price !== null ? quote?.kind ?? null : null;
    const priceAsOf = priceKind === 'close'
        ? quote?.closeDate ?? (quote?.t ? sessionDateEt(quote.t) : null)
        : null;
    const metrics = light?.metrics?.metric ?? {};
    const marketCapM = typeof metrics.marketCapitalization === 'number' ? metrics.marketCapitalization : null;
    const peRatio = typeof metrics.peTTM === 'number' && Number.isFinite(metrics.peTTM) ? metrics.peTTM : null;
    // Línea US con Finnhub sin cap o PER (caída, 429 u otro hueco del
    // proveedor — QA Tester 6 final, 19-oct-2026: megacaps N/D en una
    // ventana de despliegues con el proveedor sano): mismo respaldo del
    // backend que las no-US (cap proveedor o derivado precio x acciones,
    // PER cierre/EPS FY), declarado igual («· derivado», «· FY»).
    const backendUs = usListing && (marketCapM === null || peRatio === null)
        ? await fetchBackendMetrics(normalized)
        : null;
    const backendAll = backend ?? backendUs;
    const backendCap = backendAll && typeof backendAll.market_cap === 'number' ? backendAll.market_cap : null;
    const backendPer = backendAll && typeof backendAll.per === 'number' && Number.isFinite(backendAll.per) ? backendAll.per : null;
    const backendDerived = (backendAll?.sources ?? []).some((src) => src.toLowerCase().includes('derivada'));
    const backendPerSource = (backendAll?.sources ?? []).find((src) => src.startsWith('PER:')) ?? null;
    // Etiqueta corta de la fuente del PER de respaldo: la cadena «PER: …»
    // termina con la fuente entre paréntesis («(SEC)», «(ESEF)»…); sin ella,
    // sin etiqueta (nunca se inventa la procedencia).
    const backendPerLabel = backendPerSource?.match(/\(([^)]+)\)\s*$/)?.[1] ?? null;

    return {
        ...base,
        name: basics?.name || light?.profile?.name || normalized,
        // La divisa visible la pone SOLO el master (curado): ni la del
        // proveedor (puede ser discordante, F163) ni un «USD» asumido por
        // ser línea US — sin divisa real, número pelado.
        // Master curado manda; para no-US el backend devuelve la divisa real
        // de la compañía y la rellena cuando el master no la conoce.
        // Precio pasado a la unidad mayor (peniques -> GBP): se rotula con la
        // unidad mayor, que coincide con la del master (o la declara la
        // cotización si el master no tiene divisa).
        currency: base.currency !== null && unitDivisor === 1
            ? base.currency
            : unitDivisor !== 1 && quoteUnit ? quoteUnit.currency : backendAll?.currency ?? null,
        price,
        change:
            price === null || !hasPriorClose(quote)
                ? null
                : typeof quote?.d === 'number' && Number.isFinite(quote.d)
                  ? quote.d / unitDivisor
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
        // Fuente visible a primera vista: el PER del proveedor y el EPS TTM
        // propio (SEC) son series distintas y sin etiqueta parecen una sola
        // (QA 31-oct-2026: GOOGL PER 14,5x Finnhub vs EPS TTM SEC 19,91).
        peSourceLabel: peRatio !== null ? 'Finnhub' : backendPerLabel,
        priceKind,
        priceAsOf,
        metricsNotApplicable: !usListing,
    };
}

// ---- Monitor denso (F: watchlist monitor) ----
// Datos propios/trazables del backend research: minimo 52 semanas desde
// market_prices, proximo resultado via NASDAQ publico (mismo conector que
// /api/calendar/earnings) y comparacion con el valor justo unico (tesis
// publicada o motor, con su etiqueta de procedencia).
// Cualquier pieza sin dato llega a null: la UI pinta N/D, nunca inventa.
export type WatchlistMonitorItem = components['schemas']['WatchlistMonitorItemOut'];

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

/** Límite defensivo del batch de cotizaciones extendidas (una página entera cabe de sobras). */
const EXTENDED_QUOTES_BATCH_MAX = 100;

/**
 * Versión batch de getExtendedQuote: UNA invocación serverless por página en
 * vez de una por fila (medido en prod: 12 POSTs de acción por carga de
 * /watchlist solo para cotizaciones extendidas). Las peticiones al backend
 * salen en paralelo dentro de la misma invocación.
 */
export async function getExtendedQuotes(symbols: string[]): Promise<Record<string, ExtendedQuote | null>> {
    await requireAuthenticatedUser();
    const unique = [...new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean))].slice(0, EXTENDED_QUOTES_BATCH_MAX);
    const entries = await Promise.all(
        unique.map(async (symbol) => [symbol, await getExtendedQuote(symbol)] as const),
    );
    return Object.fromEntries(entries);
}
