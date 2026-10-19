'use server';

import { getWatchlistEntryData, getWatchlistState } from '@/lib/actions/watchlist.actions';
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
    const preview = await mapPool(items.slice(0, limit), SERVER_CONCURRENCY, async (item): Promise<HomeWatchlistItem> => {
        try {
            // Precio y divisa del LISTADO REAL (master), nunca del ticker
            // desnudo (F253/F254).
            const data = await getWatchlistEntryData(item.symbol);
            return {
                symbol: data.symbol,
                name: data.name,
                price: data.price,
                currency: data.currency,
                changePercent: data.changePercent,
                priceKind: data.priceKind,
                priceAsOf: data.priceAsOf,
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
};

export type HomeOpportunityProbe = {
    evaluated: boolean;
    opportunity: HomeOpportunity | null;
};

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
    return mapPool(candidates, SERVER_CONCURRENCY, async (sym): Promise<HomeOpportunityProbe> => {
        try {
            // Precio y divisa del LISTADO REAL (master): getStockQuote con el
            // ticker desnudo resolvia en la linea US y no traia divisa.
            const [reading, listing] = await Promise.all([getFairValueReading(sym), getWatchlistEntryData(sym)]);
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
