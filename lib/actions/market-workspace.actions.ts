'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { getCandles, getProfile, getStockQuote } from '@/lib/actions/finnhub.actions';
import { datedQuoteMetrics } from '@/lib/market/quote-metrics';
import { marketHistoryStatus } from '@/lib/market/history-status';
import { sessionDateEt } from '@/lib/market/quote-freshness';
import { fetchDatedChanges } from '@/lib/market/dated-change';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { normalizeChartCandles } from '@/lib/market/normalize-chart';
import { e2eMarketFixture, isE2EMarketFixtureEnabled } from '@/lib/e2e-market-fixture';

export type CompanyMarketSnapshot = {
    ticker: string;
    name: string;
    exchange: string | null;
    currency: string | null;
    quote: {
        price: number | null;
        change: number | null;
        changePercent: number | null;
        open: number | null;
        high: number | null;
        low: number | null;
        previousClose: number | null;
        metricsSource?: string | null;
        metricsSession?: string | null;
        // Fecha del dato mostrado como precio: cotización en vivo -> null;
        // fallback al último cierre de vela -> la fecha de esa vela, para
        // que la cabecera la rotule y no parezca precio actual.
        priceAsOf: string | null;
        // F358: frescura del precio: 'live' = sesión en curso; 'close' =
        // último cierre fechado (con fecha en priceAsOf si se conoce). Un
        // cierre NUNCA se pinta como cotización actual.
        priceKind: 'live' | 'close' | null;
    };
    // OHLC opcional: Finnhub lo sirve en la misma respuesta de velas, pero un
    // punto sin OHLC completo sigue valiendo para precio/sparkline; el chart
    // de velas filtra (toCandleRows) y muestra su propio estado vacio.
    history: Array<{
        date: string;
        open?: number | null;
        high?: number | null;
        low?: number | null;
        close: number;
        volume: number | null;
    }>;
    historySource?: string | null;
    /** Divisa que el proveedor declara en la misma respuesta de velas; null si no la trae. */
    historyCurrency?: string | null;
    status: 'available' | 'partial' | 'unavailable';
};


export type ResearchCompanyBasics = { ticker?: string; name?: string; exchange?: string; currency?: string };

// Finnhub profile2 no siempre cubre mercados no-US; la ficha research sí
// tiene la compañía (resuelve sufijos, SAN.MC -> SAN) con nombre/bolsa/moneda.
export async function getResearchCompanyBasics(ticker: string): Promise<ResearchCompanyBasics | null> {
    const backendUrl = process.env.FMP_BACKEND_URL;
    if (!backendUrl) return null;
    try {
        const path = `/api/companies/${encodeURIComponent(ticker)}`;
        const response = await fetch(`${backendUrl}${path}`, {
            headers: await researchIdentityHeaders({ method: 'GET', path }),
            signal: AbortSignal.timeout(4000),
        });
        if (!response.ok) return null;
        const data = await response.json();
        if (!data || typeof data !== 'object') return null;
        return data as ResearchCompanyBasics;
    } catch {
        return null;
    }
}

/**
 * Basics (ticker/nombre/bolsa/divisa) de varios simbolos en UNA peticion al
 * backend (GET /api/companies/basics): sustituye el fan-out de
 * getResearchCompanyBasics por simbolo de la watchlist (20+ round trips por
 * carga; oleada de 16 medida en prod a ~0,9 s, 2026-10-30).
 * Devuelve null si el backend aun no sirve el agregado (despliegue
 * escalonado front/back): el caller cae a la oleada por simbolo.
 */
export async function getResearchCompaniesBasics(
    tickers: string[],
): Promise<Record<string, ResearchCompanyBasics | null> | null> {
    const backendUrl = process.env.FMP_BACKEND_URL;
    if (!backendUrl) return null;
    const wanted = [...new Set(tickers.map((t) => t.trim().toUpperCase()).filter(Boolean))];
    if (wanted.length === 0) return {};
    try {
        const path = `/api/companies/basics`;
        const response = await fetch(`${backendUrl}${path}?tickers=${encodeURIComponent(wanted.join(','))}`, {
            headers: await researchIdentityHeaders({ method: 'GET', path }),
            signal: AbortSignal.timeout(4000),
        });
        if (!response.ok) return null;
        const data = await response.json();
        if (!data || typeof data !== 'object' || data.items === null || typeof data.items !== 'object') return null;
        const items = data.items as Record<string, ResearchCompanyBasics>;
        const out: Record<string, ResearchCompanyBasics | null> = {};
        for (const t of wanted) out[t] = items[t] ?? null;
        return out;
    } catch {
        return null;
    }
}

export async function getCompanyMarketSnapshot(ticker: string): Promise<CompanyMarketSnapshot> {
    await requireAuthenticatedUser();
    const normalized = ticker.trim().toUpperCase();
    if (isE2EMarketFixtureEnabled(process.env, normalized)) {
        return e2eMarketFixture(normalized);
    }
    const to = Math.floor(Date.now() / 1000);
    const from = to - 366 * 24 * 60 * 60;
    // El master primero: su bolsa/divisa deciden el símbolo de cotización.
    const researchCompany = await getResearchCompanyBasics(normalized);
    const quoteSymbol = quoteSymbolFor(researchCompany, normalized);
    if (!quoteSymbol) {
        // Sin identidad de listado verificada (master inaccesible) o sin
        // correspondencia de bolsa validada: cotización NO disponible. Un
        // fallo transitorio del master nunca abre la vía del ticker desnudo,
        // que puede devolver el precio de otro emisor (ALM->Almonty).
        return {
            ticker: normalized,
            name: researchCompany?.name || normalized,
            exchange: researchCompany?.exchange || null,
            currency: researchCompany?.currency || null,
            quote: { price: null, change: null, changePercent: null, open: null, high: null, low: null, previousClose: null, priceAsOf: null, priceKind: null },
            history: [],
            status: 'unavailable',
        };
    }
    const [profile, quote, candles] = await Promise.all([
        getProfile(quoteSymbol),
        getStockQuote(quoteSymbol),
        getCandles(quoteSymbol, from, to, 'D', 900),
    ]);
    const history = normalizeChartCandles(candles, { from, to, resolution: 'D' });
    const livePrice = quote?.c;
    // F358: solo se acepta cotización con frescura validada en origen
    // (sanitizeFinnhubQuote; el fallback Yahoo llega marcado como cierre).
    const quoteKind = quote?.kind === 'live' || quote?.kind === 'close' ? quote.kind : null;
    const quoteUsable = typeof livePrice === 'number' && livePrice > 0 && quoteKind !== null;
    const quoteLive = quoteUsable && quoteKind === 'live';
    const lastClose = history.at(-1) ?? null;
    // Fuera de sesión, precio, cambio y % salen del mismo cierre oficial datado
    // que Movers, Mercado y watchlist; en sesión manda la cotización en vivo.
    const dated = quoteLive ? undefined : (await fetchDatedChanges([normalized]))[normalized];
    const price = dated ? dated.price : quoteUsable ? livePrice : lastClose?.close ?? null;
    // La variación del proveedor describe ESA cotización (misma fuente y
    // payload, en vivo o en cierre fechado); sin cotización usable NO se
    // mezcla con el cierre de vela.
    const change = dated ? dated.change : quoteUsable ? quote?.d ?? null : null;
    const changePercent = dated ? dated.changePercent : quoteUsable ? quote?.dp ?? null : null;
    // Fecha del cierre: SOLO del timestamp de la propia cotización
    // (Finnhub). El fallback Yahoo no trae fecha de vela: NO se le atribuye
    // la de otra serie (la de getCandles podria no ser la del c) - queda
    // null y la cabecera rotula "precio de fecha desconocida" (F358,
    // exigencia del auditor). El fallback a vela (sin cotización) sí fecha
    // con su propia vela, que es el mismo dato que se muestra.
    const priceAsOf = quoteLive
        ? null
        : dated
          ? dated.date
          : quoteUsable
          ? quote?.t
            ? sessionDateEt(quote.t)
            : null
          : lastClose?.date ?? null;
    const metrics = datedQuoteMetrics(quote, quoteUsable);
    return {
        ticker: normalized,
        // La identidad la pone el master (curado); el perfil del proveedor
        // solo rellena huecos - nunca puede rebautizar la ficha con el
        // gemelo americano del ticker.
        name: researchCompany?.name || profile?.name || normalized,
        exchange: researchCompany?.exchange || profile?.exchange || null,
        currency: dated ? dated.currency : researchCompany?.currency || profile?.currency || null,
        quote: {
            price,
            change,
            changePercent,
            open: metrics.open,
            high: metrics.high,
            low: metrics.low,
            previousClose: dated ? dated.previousClose : metrics.previousClose,
            metricsSource: metrics.source,
            metricsSession: metrics.timestamp ? sessionDateEt(metrics.timestamp) : null,
            priceAsOf,
            priceKind: quoteLive ? 'live' : price !== null ? 'close' : null,
        },
        history,
        historySource: candles.source ?? null,
        historyCurrency: typeof candles.currency === 'string' && candles.currency.trim() ? candles.currency.trim() : null,
        // La insignia del historial describe la serie (F161): sin velas es
        // «no disponible» aunque la cotización puntual haya cargado.
        status: marketHistoryStatus(history.length),
    };
}
