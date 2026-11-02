'use server';

import { mergeSpanishListings, searchSpanishListings } from '@/lib/market/spanish-search';
import { classifyFichaCoverage, EXCHANGE_LABEL_BY_SUFFIX } from '@/lib/market/search-coverage';
import { withFetchDeadline } from '@/lib/upstream/fetch-deadline';

import { exactSymbolFirst, marketPriority, onePerIssuer } from '@/lib/market/search-results';
import { getFinnhubOnlyNews } from '@/lib/news/finnhub-only-news';
import { POPULAR_STOCK_SYMBOLS } from '@/lib/constants';
import type { PopularStocksResult } from '@/lib/popular-stocks-loader';
import { foldSearchQuery } from '@/lib/search-query';
import { cache } from 'react';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { mapBackendYahooQuote, sanitizeFinnhubQuote, type ProviderQuotePayload, type SanitizedQuote } from '@/lib/market/quote-freshness';

import { env } from '@/lib/env';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
// fetchJSON vive fuera del 'use server' a proposito: exportarlo aqui lo
// convertiria en un Server Action invocable por HTTP con una URL arbitraria
// (SSRF). Ver lib/upstream/finnhub.ts.
import { fetchJSON } from '@/lib/upstream/finnhub';

const FINNHUB_BASE_URL = env.FINNHUB_BASE_URL;

export type FinnhubCandles = { source?: string; /** Divisa de la misma respuesta del proveedor (solo la trae el backend/Yahoo). */ currency?: string; s: 'ok' | 'no_data'; c: number[]; t: number[]; o: (number | null)[]; h: (number | null)[]; l: (number | null)[]; v: (number | null)[] };

export async function getCandles(symbol: string, from: number, to: number, resolution: 'D' | 'W' | 'M' | '60' = 'D', revalidateSeconds = 1800): Promise<FinnhubCandles> {
    await requireAuthenticatedUser();
    const noData: FinnhubCandles = { s: 'no_data', c: [], t: [], o: [], h: [], l: [], v: [] };
    const token = env.FINNHUB_API_KEY;
    if (token) {
        const url = `${FINNHUB_BASE_URL}/stock/candle?symbol=${encodeURIComponent(symbol)}&resolution=${resolution}&from=${from}&to=${to}&token=${token}`;
        try {
            const result = await fetchJSON<FinnhubCandles>(url, revalidateSeconds);
            // fetchJSON puede retornar array vacío en caso de error, verificar si es un objeto válido
            if (!Array.isArray(result) && result && typeof result === 'object' && result.s === 'ok' && result.c?.length) {
                return { ...result, source: 'Finnhub' };
            }
        } catch {
            // Si el plan no permite el recurso (403) u otro error, seguimos al fallback
        }
    }
    // Fallback al backend (Yahoo chart API): Finnhub free no sirve velas de
    // mercados no-US (IBEX .MC...). Sin fallback el gráfico de la ficha sale vacío.
    const backendUrl = process.env.FMP_BACKEND_URL;
    if (backendUrl) {
        try {
            const path = `/api/market/candles/${encodeURIComponent(symbol)}`;
            const identityHeaders = await researchIdentityHeaders({ method: 'GET', path });
            const response = await fetch(`${backendUrl}${path}?from=${from}&to=${to}&resolution=${resolution}`, {
                headers: identityHeaders,
                signal: AbortSignal.timeout(8000),
            });
            if (response.ok) {
                const data = await response.json();
                if (data && data.s === 'ok' && Array.isArray(data.c) && data.c.length) {
                    return { ...data, source: data.source ?? 'Yahoo Finance' };
                }
            }
        } catch {
            // Backend caído o sin datos: estado vacío honesto
        }
    }
    return noData;
}

/** Respuesta de Finnhub `/stock/metric?metric=all`: las claves y su presencia varían por plan y mercado. */
export type FinnhubMetricsAll = { metric?: Record<string, number | string | null> };

/** Respuesta de Finnhub `/stock/price-target`. */
export type FinnhubPriceTarget = {
    symbol?: string;
    lastUpdated?: string;
    targetHigh?: number;
    targetLow?: number;
    targetMean?: number;
    targetMedian?: number;
    targetMode?: number;
};

export type FinnhubProfile2 = { ticker?: string; name?: string; exchange?: string; currency?: string; country?: string; ipo?: string; logo?: string; weburl?: string };
export const getProfile = cache(async (symbol: string): Promise<FinnhubProfile2 | null> => {
    await requireAuthenticatedUser();
    // Caché corta en memoria (60s) para llamadas en bucle (watchlist,
    // screener, market snapshot): el fetch interno ya revalida cada hora,
    // esta capa evita repetir el round-trip dentro de la ventana.
    return cachedFetch<FinnhubProfile2 | null>(
        `finnhub:profile:${symbol.trim().toUpperCase()}`,
        () => fetchProfile(symbol),
        60,
    );
});

async function fetchProfile(symbol: string): Promise<FinnhubProfile2 | null> {
    try {
        const token = env.FINNHUB_API_KEY;
        if (!token) return null;
        const url = `${FINNHUB_BASE_URL}/stock/profile2?symbol=${encodeURIComponent(symbol)}&token=${token}`;
        const result = await fetchJSON<FinnhubProfile2>(url, 3600);
        // fetchJSON puede retornar array vacío en caso de error, verificar si es un objeto válido
        if (Array.isArray(result) || result === null || result === undefined) {
            return null;
        }
        return result;
    } catch {
        return null;
    }
}

export async function getNews(symbols?: string[]): Promise<MarketNewsArticle[]> {
    await requireAuthenticatedUser();
    try {
        // Use new multi-source news aggregation for better coverage
        const { getNewsWithFallback } = await import('./newsSources.actions');
        const news = await getNewsWithFallback(symbols, 6);

        // If multi-source returns results, use them
        if (news && news.length > 0) {
            return news;
        }

        // Fallback a Finnhub directo: la misma lógica que la fuente Finnhub
        // del agregador multi-fuente (lib/news/finnhub-only-news).
        return await getFinnhubOnlyNews(symbols, 6);
    } catch (err) {
        console.error('getNews error:', err);
        throw new Error('Failed to fetch news');
    }
}

/**
 * Métricas de valoración (cap, PER) y nombre de perfil para LISTADOS.
 * La watchlist solo consumía metric + profile2 de getStockFinancialDataLight,
 * pero esa versión pedía además /quote (duplicada: la página ya llama a
 * getStockQuote) y /stock/price-target (sin uso): 2 llamadas Finnhub más
 * por símbolo y página, contra la cuota compartida del plan free.
 */
export async function getStockValuationBasics(symbol: string): Promise<{
    profile: FinnhubProfile2 | null;
    metrics: FinnhubMetricsAll;
} | null> {
    await requireAuthenticatedUser();
    try {
        const token = env.FINNHUB_API_KEY;
        if (!token) {
            return null;
        }
        const [profile, metrics] = await Promise.all([
            fetchJSON<FinnhubProfile2>(`${FINNHUB_BASE_URL}/stock/profile2?symbol=${encodeURIComponent(symbol)}&token=${token}`, 86400).catch(() => null),
            fetchJSON<FinnhubMetricsAll>(`${FINNHUB_BASE_URL}/stock/metric?symbol=${encodeURIComponent(symbol)}&metric=all&token=${token}`, 86400).catch(() => ({ metric: {} })),
        ]);
        return { profile, metrics };
    } catch {
        return null;
    }
}

export async function getStockFinancialDataLight(symbol: string): Promise<{
    quote: SanitizedQuote | null;
    profile: FinnhubProfile2 | null;
    metrics: FinnhubMetricsAll;
    priceTarget: FinnhubPriceTarget | null;
} | null> {
    await requireAuthenticatedUser();
    try {
        const token = env.FINNHUB_API_KEY;
        if (!token) {
            return null;
        }

        // Only fetch essential data - no news, events, peers etc.
        const [quote, profile, metrics, priceTarget] = await Promise.all([
            fetchJSON<ProviderQuotePayload>(`${FINNHUB_BASE_URL}/quote?symbol=${encodeURIComponent(symbol)}&token=${token}`, 60).then(sanitizeFinnhubQuote).catch(() => null), // F358: validada por timestamp
            fetchJSON<FinnhubProfile2>(`${FINNHUB_BASE_URL}/stock/profile2?symbol=${encodeURIComponent(symbol)}&token=${token}`, 86400).catch(() => null),
            fetchJSON<FinnhubMetricsAll>(`${FINNHUB_BASE_URL}/stock/metric?symbol=${encodeURIComponent(symbol)}&metric=all&token=${token}`, 86400).catch(() => ({ metric: {} })),
            fetchJSON<FinnhubPriceTarget>(`${FINNHUB_BASE_URL}/stock/price-target?symbol=${encodeURIComponent(symbol)}&token=${token}`, 86400).catch(() => null),
        ]);

        return { quote, profile, metrics, priceTarget };
    } catch {
        // Silently fail for light version
        return null;
    }
}


function exchangeFromDisplaySymbol(displaySymbol?: string): string | undefined {
    if (!displaySymbol) return undefined;
    const idx = displaySymbol.lastIndexOf('.');
    if (idx < 0) return 'US';
    const suffix = displaySymbol.slice(idx + 1).toUpperCase();
    // Sufijo desconocido: se muestra tal cual (el comentario del mapa ya lo
    // prometía, pero el `|| 'US'` del llamador lo convertía en «US» y
    // tickers como 300183.SZ o TMAS.JK salían etiquetados como EE. UU.).
    return EXCHANGE_LABEL_BY_SUFFIX[suffix] ?? suffix;
}

// Finnhub profile2 devuelve la bolsa en texto largo inglés
// («NASDAQ NMS - GLOBAL MARKET»); el buscador la muestra literal.
function normalizeExchangeLabel(exchange?: string): string | undefined {
    if (!exchange) return undefined;
    const up = exchange.toUpperCase();
    if (up.includes('NASDAQ')) return 'NASDAQ';
    if (up.includes('NYSE AMERICAN')) return 'NYSE American';
    if (up.includes('NYSE ARCA')) return 'NYSE Arca';
    if (up.includes('NEW YORK STOCK EXCHANGE')) return 'NYSE';
    if (up.includes('BATS') || up.includes('CBOE')) return 'Cboe';
    return exchange;
}

const searchStocksOrThrow = async (query?: string): Promise<StockWithWatchlistStatus[]> => {    await requireAuthenticatedUser();
    {
        const token = env.FINNHUB_API_KEY;
        if (!token) {
            // Finnhub is optional; the search command renders an explicit empty state.
            return [];
        }

        const trimmed = typeof query === 'string' ? foldSearchQuery(query) : '';

        let results: FinnhubSearchResult[] = [];

        if (!trimmed) {
            // Populares con estado honesto: 0/10 perfiles con clave
            // configurada es un fallo del proveedor, no "no hay acciones".
            const popular = await getPopularStocks();
            if (popular.status === 'error') {
                throw new Error('finnhub popular profiles unavailable');
            }
            return popular.stocks;
        } else {
            const url = `${FINNHUB_BASE_URL}/search?q=${encodeURIComponent(trimmed)}&token=${token}`;
            const data = await fetchJSON<FinnhubSearchResponse>(url, 1800, 3500);
            results = Array.isArray(data?.result) ? data.result : [];

            // Un ticker exacto con sufijo de bolsa ("SAN.MC") no matchea en el
            // search de Finnhub (el punto rompe el prefix matching), asi que
            // escribir el simbolo tal cual no devolvia nada y no se podian
            // anadir posiciones EU por ticker. Fallback: busca la parte base
            // ("SAN") y quedate con el resultado cuyo simbolo coincida
            // exactamente con lo pedido, anteponiendolo al resto.
            const upperQuery = trimmed.toUpperCase();
            const matchesExact = (r: FinnhubSearchResult): boolean =>
                (r.symbol || '').toUpperCase() === upperQuery ||
                (r.displaySymbol || '').toUpperCase() === upperQuery;
            if (upperQuery.includes('.') && !results.some(matchesExact)) {
                const base = upperQuery.slice(0, upperQuery.indexOf('.'));
                if (base) {
                    try {
                        const fbUrl = `${FINNHUB_BASE_URL}/search?q=${encodeURIComponent(base)}&token=${token}`;
                        const fbData = await fetchJSON<FinnhubSearchResponse>(fbUrl, 1800, 1000);
                        const fbResults = Array.isArray(fbData?.result) ? fbData.result : [];
                        const exact = fbResults.filter(matchesExact);
                        if (exact.length > 0) {
                            results = [...exact, ...results];
                        }
                    } catch {
                        // Fallback opcional: si falla, devolvemos lo que hubiera.
                    }
                }
            }
        }

        // Finnhub busca AMZ por símbolo y devuelve AMZ.DE/AMZ.F, pero omite
        // AMZN. Consulta acotada por el nombre REAL del primer listado (no se
        // inventa ningún alias): solo admite el mismo nombre normalizado y un
        // símbolo que empiece por la query. Beneficia a todos los buscadores.
        const prefix = trimmed.toUpperCase();
        if (/^[A-Z]{2,5}$/.test(prefix) && !results.some(r => !r.symbol.includes('.') && r.symbol.toUpperCase().startsWith(prefix))) {
            const listing = results.find(r => r.symbol.toUpperCase().startsWith(`${prefix}.`) && r.description);
            if (listing) {
                try {
                    const byName = await fetchJSON<FinnhubSearchResponse>(`${FINNHUB_BASE_URL}/search?q=${encodeURIComponent(listing.description)}&token=${token}`, 1800, 1000);
                    const foldName = (text: string) => foldSearchQuery(text).toUpperCase().replace(/[^A-Z0-9]/g, '');
                    const verified = (byName.result ?? []).filter(r => r.symbol.toUpperCase().startsWith(prefix) && foldName(r.description) === foldName(listing.description));
                    results = [...verified, ...results];
                } catch {
                    // Enriquecimiento opcional: conserva los listados originales.
                }
            }
        }

        // Ticker desnudo sin resultado exacto (ASTS): el search de Finnhub ordena
        // por nombre y puede no devolverlo; el perfil por simbolo es exacto.
        const bare = trimmed.toUpperCase();
        if (/^[A-Z][A-Z0-9-]{0,5}$/.test(bare) && !results.some((r) => (r.symbol || '').toUpperCase() === bare)) {
            try {
                const profile = await getProfile(bare);
                if (profile?.name) {
                    results = [{ symbol: bare, displaySymbol: bare, description: profile.name, type: 'Common Stock' } as FinnhubSearchResult, ...results];
                }
            } catch {
                // Fallback opcional.
            }
        }

        const ordered = marketPriority(onePerIssuer(exactSymbolFirst(results, trimmed), trimmed), trimmed);
        const mapped: StockWithWatchlistStatus[] = ordered
            .map((r) => {
                const upper = (r.symbol || '').toUpperCase();
                const name = r.description || upper;
                // displaySymbol es el ticker visible (SAN.MC), NO la bolsa:
                // solo se usa para derivar el mercado por sufijo. (El campo
                // `__exchange` que se leía aquí no lo escribía nadie.)
                const exchange = exchangeFromDisplaySymbol(r.displaySymbol as string | undefined) || 'US';
                const type = r.type || 'Stock';
                const item: StockWithWatchlistStatus = {
                    symbol: upper,
                    name,
                    exchange,
                    type,
                    isInWatchlist: false,
                };
                return item;
            })
            // Finnhub devuelve el mismo simbolo varias veces (AENA.MC x2): una sola entrada.
            .filter((item, index, all) => all.findIndex((other) => other.symbol === item.symbol) === index)
            .slice(0, 15);

        return mapped;
    }
};

export type SearchStocksResult =
    | { status: 'ok'; stocks: StockWithWatchlistStatus[] }
    | { status: 'error'; stocks: [] };

/** Búsqueda con ESTADO explícito (F215): con la cuota de Finnhub agotada el
 *  buscador global afirmaba "Sin resultados" para AAPL porque el error se
 *  tragaba y volvía como []. Aquí el fallo de proveedor/red es `error` y la
 *  UI lo dice en vez de mentir. */
/** Item del master propio (GET /api/companies/search). */
type MasterSearchItem = { ticker?: string; name?: string; exchange?: string; currency?: string };

/**
 * Busqueda en el master propio (backend), SIN cuota de proveedor: primera
 * fuente del buscador. Devuelve tickers canonicos (SAN, no SAN.MC) con
 * nombre/bolsa reales. Fallos -> []: el caller conserva la via Finnhub.
 */
async function searchMasterCompanies(query: string): Promise<StockWithWatchlistStatus[]> {
    const backendUrl = process.env.FMP_BACKEND_URL;
    const trimmed = foldSearchQuery(query);
    if (!backendUrl || !trimmed) return [];
    try {
        const path = '/api/companies/search';
        const identityHeaders = await researchIdentityHeaders({ method: 'GET', path });
        const response = await fetch(`${backendUrl}${path}?q=${encodeURIComponent(trimmed)}&limit=15`, {
            headers: identityHeaders,
            signal: AbortSignal.timeout(2500),
        });
        if (!response.ok) return [];
        const data = await response.json();
        const rows: MasterSearchItem[] = Array.isArray(data?.results) ? data.results : [];
        return rows
            .filter((r) => r?.ticker && r?.name)
            .map((r) => ({
                symbol: String(r.ticker).toUpperCase(),
                name: String(r.name),
                exchange: (r.exchange ?? '').trim(),
                type: 'Common Stock',
                isInWatchlist: false,
            }));
    } catch {
        return [];
    }
}

export const searchStocksWithStatus = cache(async (query?: string): Promise<SearchStocksResult> => {
    await requireAuthenticatedUser();
    // Unsupported search input is an empty query result, not provider failure.
    if (typeof query === 'string' && (query.length > 120 || /[<>\x00-\x1f]/.test(query))) {
        return { status: 'ok', stocks: [] };
    }
    const local = searchSpanishListings(query ?? '');
    // Master propio primero: sin cuota de proveedor y con tickers canonicos.
    // Cuando Finnhub agota su cuota free (60 req/min compartida por toda la
    // app; la quema la propia watchlist, medido 2026-10-30) el buscador
    // seguia fallando para cualquier empresa no espanola («Amzn» -> «fallo
    // del proveedor») pese a tenerla en nuestro registro.
    const master = await searchMasterCompanies(query ?? '');
    const coveredSymbols = new Set(local.map((row) => row.symbol.toUpperCase()));
    const withCoverage = (stocks: StockWithWatchlistStatus[]): StockWithWatchlistStatus[] =>
        stocks.map((stock) => ({
            ...stock,
            fichaCoverage: classifyFichaCoverage(stock.symbol, coveredSymbols.has(stock.symbol.toUpperCase())),
        }));
    try {
        const remote = await withFetchDeadline(() => searchStocksOrThrow(query), 4500);
        return { status: 'ok', stocks: withCoverage(mergeSpanishListings(query ?? '', local, [...master, ...remote])) };
    } catch (err) {
        console.error('Error in stock search:', err);
        // Fallback local + master: ambos caminos conservan la anotacion de
        // cobertura de ficha (withCoverage es idempotente).
        const fallback = mergeSpanishListings(query ?? '', withCoverage(local), withCoverage(master));
        if (fallback.length) return { status: 'ok', stocks: fallback };
        return { status: 'error', stocks: [] };
    }
});

/**
 * Populares del buscador con ESTADO explicito: un fallo total de
 * proveedor/red devuelve `error` (el caller reintenta y avisa); la lista
 * vacia valida (sin clave Finnhub) es `ok` con []. Un [] a secas seria
 * indistinguible de "no hay nada que mostrar".
 */
export const getPopularStocks = cache(async (): Promise<PopularStocksResult> => {
    await requireAuthenticatedUser();
    const token = env.FINNHUB_API_KEY;
    if (!token) {
        // Finnhub es opcional: lista vacia valida, no un fallo.
        return { status: 'ok', stocks: [] };
    }
    const top = POPULAR_STOCK_SYMBOLS.slice(0, 10);
    const profiles = await Promise.all(
        top.map(async (sym) => {
            try {
                const url = `${FINNHUB_BASE_URL}/stock/profile2?symbol=${encodeURIComponent(sym)}&token=${token}`;
                const profile = await fetchJSON<FinnhubProfile2>(url, 3600);
                return { sym, profile } as { sym: string; profile: FinnhubProfile2 | null };
            } catch {
                return { sym, profile: null } as { sym: string; profile: FinnhubProfile2 | null };
            }
        })
    );
    const successful = profiles.filter(
        (r): r is { sym: string; profile: FinnhubProfile2 } => Boolean(r.profile?.name || r.profile?.ticker),
    );
    if (successful.length === 0) {
        // 0/10 con clave configurada: proveedor o red caidos. NO se cachea
        // como exito: el buscador reintentara y mostrara indicador.
        return { status: 'error' };
    }
    const stocks: StockWithWatchlistStatus[] = successful
        .map(({ sym, profile }) => {
            const symbol = sym.toUpperCase();
            return {
                symbol,
                name: profile.name || profile.ticker || symbol,
                exchange: normalizeExchangeLabel(profile.exchange) || 'US',
                type: 'Common Stock',
                isInWatchlist: false,
            };
        })
        .slice(0, 10);
    return { status: 'ok', stocks };
});

// Helper para obtener solo la cotización (más ligero que getStockFinancialData)
export async function getStockQuote(symbol: string): Promise<StockQuote | null> {
    await requireAuthenticatedUser();
    // Caché corta en memoria (45s): quote se llama en bucle (watchlist,
    // screener, oportunidades) y el dato es idéntico dentro de la ventana.
    // Los misses (null) no se cachean.
    return cachedFetch(
        `finnhub:quote:${symbol.trim().toUpperCase()}`,
        () => fetchStockQuote(symbol),
        45,
    );
}

/** F358: cotizacion con frescura validada; la logica vive en el modulo
 * puro lib/market/quote-freshness (testeable con node --test). */
export type StockQuote = SanitizedQuote;

async function fetchStockQuote(symbol: string): Promise<StockQuote | null> {
    // Try Finnhub first
    try {
        const token = env.FINNHUB_API_KEY;
        if (token) {
            const url = `${FINNHUB_BASE_URL}/quote?symbol=${encodeURIComponent(symbol)}&token=${token}`;
            const data = await fetchJSON<ProviderQuotePayload>(url, 60);
            // Verify we got valid data (Finnhub returns all zeros for invalid
            // symbols) y fresca (F358: la Data Cache sirve el ultimo valor
            // bueno indefinidamente bajo 429 sostenidos - stale-while-error).
            const quote = sanitizeFinnhubQuote(data);
            if (quote) {
                return quote;
            }
        }
    } catch {
        console.log('Finnhub quote failed for %s, trying Yahoo Finance...', symbol);
    }
    
    // Fallback al backend (Yahoo chart API) para mercados que Finnhub free
    // no cubre (IBEX .MC, .PA, .DE...). El backend cachea 60s por símbolo.
    const backendUrl = process.env.FMP_BACKEND_URL;
    if (backendUrl) {
        try {
            const path = `/api/market/quote/${encodeURIComponent(symbol)}`;
            const identityHeaders = await researchIdentityHeaders({
                method: 'GET',
                path,
            });
            const response = await fetch(`${backendUrl}${path}`, {
                headers: identityHeaders,
                // Timeout acotado: un backend caído no debe congelar la página.
                signal: AbortSignal.timeout(5000),
            });
            if (response.ok) {
                const data = await response.json();
                // Provenance Yahoo (cierres diarios, SIN timestamp de la
                // vela exacta): NUNCA se pinta como cotizacion en vivo y NO se
                // le atribuye la fecha de otra serie (F358, exigencia del
                // auditor) - el consumidor rotula "precio de fecha desconocida".
                const yahooQuote = mapBackendYahooQuote(data);
                if (yahooQuote) {
                    return yahooQuote;
                }
            }
        } catch (error) {
            console.error('Yahoo Finance quote also failed for %s:', symbol, error);
        }
    }
    
    return null;
}

