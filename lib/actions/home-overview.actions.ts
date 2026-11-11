'use server';

import { getWatchlistEntryData, getWatchlistState } from '@/lib/actions/watchlist.actions';
import { getResearchCompaniesBasics, getResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { probeQuoteFromBackend, type ProbeQuote } from '@/lib/market/probe-quote';
import type { ProviderQuotePayload } from '@/lib/market/quote-freshness';
import { researchRequest } from '@/lib/research/client';
import { fetchDatedChanges, type DatedChange } from '@/lib/market/dated-change';
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
    const pageSymbols = pageItems.map((item) => item.symbol);
    // Mismo patrón que la página /watchlist (medido en prod): cierres
    // datados, masters y cotizaciones se lanzan A LA VEZ; antes los cierres
    // se esperaban en serie y el master era un GET /api/companies/{ticker}
    // por símbolo (N peticiones) seguido de la cadena quote/metrics por
    // símbolo, y la sección entera del inicio esperaba esa suma (344 ms
    // medidos frente a 64 ms de cartera, 11-nov-2026).
    const datedChangesPromise = fetchDatedChanges(pageSymbols);
    // El master (nombre, bolsa, divisa) en UNA petición agregada al backend,
    // fuera del presupuesto: conserva nombre/divisa aunque la cotización
    // agote el suyo. Si el backend aún no sirve el agregado (despliegue
    // escalonado front/back) se mantiene la oleada por símbolo.
    const batchedBasics = await getResearchCompaniesBasics(pageSymbols);
    const basicsPromises = pageItems.map((item) => {
        const symbol = item.symbol.trim().toUpperCase();
        return batchedBasics
            ? Promise.resolve(batchedBasics[symbol] ?? null)
            : getResearchCompanyBasics(symbol);
    });
    // Presupuesto por símbolo (mismo tope de 3 s que /watchlist): en una
    // instancia fría la cadena de cotización estiraba la sección a 7-9 s.
    // Pasado el tope la tarjeta usa el CIERRE DATADO etiquetado (misma
    // fuente que watchlist, Movers y Mercado, F358), nunca un «sin datos»
    // fabricado ni una espera ilimitada. Las lecturas siguen en vuelo y
    // calientan las cachés para la siguiente carga.
    const ENTRY_DATA_BUDGET_MS = 3000;
    const entryPromises = pageItems.map((item, index) => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        return Promise.race([
            basicsPromises[index].then((basics) => getWatchlistEntryData(item.symbol, basics)),
            new Promise<null>((resolve) => {
                timer = setTimeout(() => resolve(null), ENTRY_DATA_BUDGET_MS);
            }),
        ]).then(
            (value) => {
                // Sin clearTimeout el temporizador colgado mantiene la
                // instancia serverless despierta tras responder.
                if (timer) clearTimeout(timer);
                return value;
            },
            () => {
                if (timer) clearTimeout(timer);
                return null;
            },
        );
    });
    const [datedChanges, basicsList, entries] = await Promise.all([
        datedChangesPromise.catch((): Record<string, DatedChange> => ({})),
        Promise.all(basicsPromises.map((promise) => promise.catch(() => null))),
        Promise.all(entryPromises),
    ]);
    const preview = pageItems.map((item, index): HomeWatchlistItem => {
        const symbol = item.symbol.trim().toUpperCase();
        const basics = basicsList[index] ?? null;
        const entry = entries[index];
        // Misma regla que la página de watchlist: la cotización viva manda
        // solo cuando es realmente 'live'; en cualquier otro caso manda el
        // cierre datado etiquetado (CGEO.L: «Cierre 19 oct 0,00%» en inicio
        // frente a «Cierre 16 oct -0,82%» en watchlist, 19 oct 2026).
        const dated = entry && entry.priceKind === 'live'
            ? undefined
            : datedChanges[entry?.symbol ?? symbol] ?? datedChanges[item.symbol] ?? datedChanges[symbol];
        if (dated) {
            return {
                symbol,
                name: entry?.name ?? basics?.name ?? symbol,
                price: dated.price,
                currency: dated.currency,
                changePercent: dated.changePercent,
                priceKind: 'close',
                priceAsOf: dated.date,
            };
        }
        if (entry) {
            return {
                symbol: entry.symbol,
                name: entry.name,
                price: entry.price,
                currency: entry.currency,
                changePercent: entry.changePercent,
                priceKind: entry.priceKind,
                priceAsOf: entry.priceAsOf,
            };
        }
        // Presupuesto agotado o proveedor caído sin cierre datado: N/D
        // honesto, pero CON nombre y divisa del master si se resolvió (un
        // cierre en € no sale en $); nunca se fabrica un 0.
        return { symbol, name: basics?.name ?? symbol, price: null, currency: basics?.currency ?? null, changePercent: null, priceKind: null, priceAsOf: null };
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
