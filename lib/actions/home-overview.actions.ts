'use server';

import { getWatchlistEntryData, getWatchlistState } from '@/lib/actions/watchlist.actions';
import { probeQuoteFromBackend, type ProbeQuote } from '@/lib/market/probe-quote';
import type { ProviderQuotePayload } from '@/lib/market/quote-freshness';
import { researchRequest } from '@/lib/research/client';
import { fetchDatedChanges } from '@/lib/market/dated-change';
import { getFairValueReading, getScreenerStocksReal } from '@/lib/actions/screener.actions';
import { DCF_MIN_UPSIDE_PCT } from '@/lib/overview/dcf-candidates';

/**
 * Lecturas agregadas del inicio.
 *
 * Next serializa las server actions que lanza un mismo cliente: cada una
 * espera a que acabe la anterior. El inicio hacia ~20 llamadas sueltas (una
 * por simbolo para precio y DCF) y la ultima tardaba ~9 s en empezar. Aqui
 * el fan-out por simbolo ocurre en el servidor, con concurrencia acotada
 * para no saturar el limitador del backend, y el cliente hace una sola
 * llamada por seccion.
 */

const SERVER_CONCURRENCY = 3;

async function mapPool<T, R>(items: T[], size: number, fn: (item: T) => Promise<R>): Promise<R[]> {
    const out = new Array<R>(items.length);
    let next = 0;
    const worker = async () => {
        while (next < items.length) {
            const index = next++;
            out[index] = await fn(items[index]);
        }
    };
    await Promise.all(Array.from({ length: Math.min(size, items.length) }, worker));
    return out;
}

export type HomeWatchlistItem = {
    symbol: string;
    name: string;
    // null = sin cotizacion disponible: nunca se fabrica un 0.
    price: number | null;
    currency: string | null;
    changePercent: number | null;
    // F358: frescura del precio; un cierre se etiqueta con su fecha si la fuente la da.
    priceKind: 'live' | 'close' | null;
    priceAsOf: string | null;
};

export type HomeWatchlistPreview = {
    unavailable: boolean;
    total: number;
    items: HomeWatchlistItem[];
};

export async function getHomeWatchlistPreview(limit: number): Promise<HomeWatchlistPreview> {
    const { items, unavailable } = await getWatchlistState();
    if (unavailable) return { unavailable: true, total: 0, items: [] };
    const pageItems = items.slice(0, limit);
    // Mismo cierre datado y mismo % que watchlist, Movers y Mercado
    // (/api/market/changes sobre market_prices): antes la vista previa del
    // inicio se quedaba con el cierre de la cadena viva Finnhub->Yahoo y
    // mostraba otra fecha y otro cambio para el mismo símbolo (CGEO.L:
    // "Cierre 19 oct 0,00%" en inicio frente a "Cierre 16 oct -0,82%" en
    // watchlist, 19 oct 2026). Misma regla que la página de watchlist: la
    // cotización viva manda solo cuando es realmente 'live'.
    const datedChanges = await fetchDatedChanges(pageItems.map((item) => item.symbol));
    const preview = await mapPool(pageItems, SERVER_CONCURRENCY, async (item): Promise<HomeWatchlistItem> => {
        try {
            // Precio y divisa del LISTADO REAL (master), nunca del ticker
            // desnudo (F253/F254).
            const data = await getWatchlistEntryData(item.symbol);
            const dated = data.priceKind === 'live' ? undefined : datedChanges[data.symbol];
            return {
                symbol: data.symbol,
                name: data.name,
                price: dated ? dated.price : data.price,
                currency: dated ? dated.currency : data.currency,
                changePercent: dated ? dated.changePercent : data.changePercent,
                priceKind: dated ? 'close' : data.priceKind,
                priceAsOf: dated ? dated.date : data.priceAsOf,
            };
        } catch {
            return { symbol: item.symbol, name: item.symbol, price: null, currency: null, changePercent: null, priceKind: null, priceAsOf: null };
        }
    });
    return { unavailable: false, total: items.length, items: preview };
}

export type HomeOpportunity = {
    symbol: string;
    name: string;
    price: number;
    currency: string | null;
    fairValue: number;
    upside: number;
    /** true = el DCF no es publicable: orientacion del motor, no valoracion final. */
    orientation?: boolean;
    /** Procedencia del valor justo único («Tesis publicada v3», «Motor de valoración»…). */
    fairValueLabel?: string;
    fairValueAsOf?: string | null;
};

export type HomeOpportunityProbe = {
    evaluated: boolean;
    opportunity: HomeOpportunity | null;
};

/** Lote del backend: UNA llamada para las N candidatas del sondeo (Yahoo con
 * cache Redis compartida de 60s) en vez de N fetches Finnhub/Yahoo desde
 * Vercel con cache en memoria por instancia. Medido 2026-10-31: el POST del
 * bundle de Inicio tardaba 6.959 ms y la cuota Finnhub free (60 req/min
 * compartida por toda la app) se agotaba con pocas cargas. Simbolo sin dato
 * en el lote -> fallback por candidata (getWatchlistEntryData). */
async function fetchProbeQuotes(symbols: string[]): Promise<Map<string, ProbeQuote>> {
    const out = new Map<string, ProbeQuote>();
    if (symbols.length === 0) return out;
    try {
        const data = await researchRequest<{ quotes?: Record<string, ProviderQuotePayload | null> }>(
            '/api/market/quotes/batch',
            { method: 'POST', body: JSON.stringify({ symbols }) },
        );
        for (const [sym, payload] of Object.entries(data?.quotes ?? {})) {
            const probe = probeQuoteFromBackend(payload);
            if (probe) out.set(sym, probe);
        }
    } catch {
        // El lote caido no rompe el sondeo: cada candidata usa su camino propio.
    }
    return out;
}

export async function getHomeOpportunities(params: {
    marketCapMoreThan: number;
    limit: number;
    candidateLimit: number;
}): Promise<HomeOpportunityProbe[]> {
    const screener = await getScreenerStocksReal({
        marketCapMoreThan: params.marketCapMoreThan,
        limit: params.limit,
    });
    // Se prueban primero las candidatas con fundamentales persistidos (sin ellos
    // el DCF no es calculable); orden estable dentro de cada grupo.
    const withFundamentals = screener.filter((row) => row.has_fundamentals).map((row) => row.symbol);
    const withoutFundamentals = screener.filter((row) => !row.has_fundamentals).map((row) => row.symbol);
    const candidates = [...withFundamentals, ...withoutFundamentals].slice(0, params.candidateLimit);
    const probeQuotes = await fetchProbeQuotes(candidates);
    return mapPool(candidates, SERVER_CONCURRENCY, async (sym): Promise<HomeOpportunityProbe> => {
        try {
            // Precio y divisa del LISTADO REAL (master): getStockQuote con el
            // ticker desnudo resolvia en la linea US y no traia divisa.
            const batched = probeQuotes.get(sym.trim().toUpperCase()) ?? null;
            const [reading, listing] = await Promise.all([
                getFairValueReading(sym),
                batched ? Promise.resolve(batched) : getWatchlistEntryData(sym),
            ]);
            const currentPrice = listing.price ?? 0;
            if (reading && currentPrice > 0) {
                const upside = ((reading.value - currentPrice) / currentPrice) * 100;
                return {
                    evaluated: true,
                    opportunity: upside > DCF_MIN_UPSIDE_PCT
                        ? {
                            symbol: sym,
                            name: sym,
                            price: currentPrice,
                            currency: listing.currency,
                            fairValue: reading.value,
                            upside,
                            // Sin publishable el valor es una orientacion del motor,
                            // nunca una valoracion final: la ficha lo declara.
                            orientation: !reading.publishable,
                            fairValueLabel: reading.label,
                            fairValueAsOf: reading.asOf,
                        }
                        : null,
                };
            }
            return { evaluated: false, opportunity: null };
        } catch {
            return { evaluated: false, opportunity: null };
        }
    });
}
