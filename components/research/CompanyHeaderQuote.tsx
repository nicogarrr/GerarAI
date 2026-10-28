'use client';

import { use, useEffect, useRef, useState } from 'react';
import { NA, formatMarketDate, formatMoney, formatPercent, formatPrice, isValidCurrencyCode } from '@/lib/format';
import { extendedQuoteLabel, quoteDate, quoteTime, quoteSessionDate, type ExtendedQuote } from '@/lib/market/extended-quote';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { chartFallbackCurrency } from '@/lib/market/chart-fallback-currency';
import { isClosedCandle } from '@/lib/market/candle-close';
import { CompanyTechnicalWorkspace } from './CompanyTechnicalWorkspace';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';

/** USD prices follow the user's English style; other listings keep their own currency. */
function headerMoney(value: number | null | undefined, currency: string): string {
    if (currency === 'USD' && value != null && Number.isFinite(value)) {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
    }
    return formatMoney(value, currency);
}

/** Variación en divisa: magnitudes < 0,01 con dígitos significativos (F35),
 *  nunca un «0» redondeado junto a un porcentaje distinto de cero (TEF:
 *  «0 · -0,06 %» cuando la variación real era -0,002 €). */
function headerChangeMoney(value: number, currency: string): string {
    return formatPrice(value, currency, { signDisplay: 'exceptZero' });
}

/** One timestamped Yahoo payload supplies the price and all header metrics. */
export function CompanyHeaderQuote({
    snapshot,
    initialQuote,
}: {
    snapshot: CompanyMarketSnapshot;
    /** Lectura de cotizacion lanzada en servidor al conocer el listado (nunca rechaza: null = fallo). */
    initialQuote?: Promise<ExtendedQuote | null>;
}) {
    // Una cotizacion de servidor valida evita la espera de hidratar + pedirla
    // desde el cliente. Sin ella (null/undefined) todo sigue como antes.
    const serverRead = initialQuote ? use(initialQuote) : null;
    const serverQuote = serverRead && serverRead.status !== 'unavailable' ? serverRead : null;
    const serverQuoteRef = useRef(serverQuote);
    const [quote, setQuote] = useState<ExtendedQuote | null>(serverQuote);
    // false hasta que la primera lectura termina (con precio o sin él): antes
    // de eso no hay «N/D» que declarar, solo una carga en curso.
    const [settled, setSettled] = useState(serverQuote !== null);
    // Pasados 4 s sin cotización, la cabecera cae al último cierre del gráfico.
    const [slow, setSlow] = useState(false);
    // Resolve the actual listing, never a naked non-US ticker's US namesake.
    const symbol = quoteSymbolFor({ exchange: snapshot.exchange ?? undefined, currency: snapshot.currency ?? undefined }, snapshot.ticker);
    const recoverListing = !symbol;
    const requestTicker = symbol ?? snapshot.ticker;
    useEffect(() => {
        let disposed = false;
        let inFlight = false;
        let lastRead = 0;
        let activeSession = true;
        const controller = new AbortController();
        // Solo la primera ejecucion para este simbolo puede usar la lectura de
        // servidor (ya sirve de lectura inicial); un cambio de simbolo la descarta.
        const seeded = serverQuoteRef.current;
        serverQuoteRef.current = null;
        if (seeded) {
            lastRead = Date.now();
            activeSession = seeded.session === 'regular' || seeded.session === 'pre' || seeded.session === 'post';
        } else {
            setQuote(null);
            setSettled(false);
        }
        const refresh = async (initial = false) => {
            // The first read always runs: a tab opened in the background (or a
            // headless browser) must not stay on N/D forever. Only the polling
            // pauses while hidden.
            if (!requestTicker || (!initial && document.visibilityState !== 'visible') || inFlight) return;
            if (!initial && Date.now() - lastRead < 300_000) return;
            lastRead = Date.now();
            inFlight = true;
            try {
                const response = await fetch(`/api/companies/${encodeURIComponent(requestTicker)}/extended-quote${recoverListing ? '?resolveListing=1' : ''}`, {
                    cache: 'no-store', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]),
                });
                const value = response.ok ? await response.json() as ExtendedQuote : null;
                activeSession = value?.session === 'regular' || value?.session === 'pre' || value?.session === 'post';
                if (!disposed) {
                    setQuote(value?.status !== 'unavailable' ? value : null);
                    setSettled(true);
                }
            } catch {
                if (!disposed) {
                    setQuote(null); // No stale-on-error price.
                    setSettled(true);
                }
            } finally { inFlight = false; }
        };
        if (!seeded) void refresh(true);
        // Closed sessions need a low-frequency recovery read: no exchange
        // calendar is supplied by the API, so never guess opening hours or
        // freeze a tab forever after a weekend/error.
        const interval = window.setInterval(() => {
            if (activeSession || Date.now() - lastRead >= 1_800_000) void refresh();
        }, 300_000);
        const onVisibility = () => { if (document.visibilityState === 'visible') void refresh(); };
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            disposed = true;
            controller.abort();
            window.clearInterval(interval);
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [requestTicker, recoverListing]);
    useEffect(() => {
        if (settled) return;
        const timer = window.setTimeout(() => setSlow(true), 4000);
        return () => window.clearTimeout(timer);
    }, [settled, requestTicker]);
    const quoteCurrency = quote?.currency ?? null;
    const label = extendedQuoteLabel(quote);
    const showPrice = label !== NA && quote?.price != null && isValidCurrencyCode(quoteCurrency);
    const signBase = quote?.change ?? quote?.change_percent ?? 0;
    // «Cierre regular» repite «Cierre anterior» cuando ambos son el mismo dato: se muestra una sola vez.
    const duplicatedClose = quote?.regular_close != null && quote.regular_close === quote.previous_close;
    // Fallback honesto: último cierre de las velas del gráfico (mismo dato que
    // pinta el gráfico), rotulado con su fecha. Nunca se presenta como precio en
    // vivo ni se rellenan métricas que la vela no trae.
    const last = snapshot.history.at(-1) ?? null;
    const prev = snapshot.history.at(-2) ?? null;
    const fallbackPrice = last?.close ?? null;
    // Listados en subunidad (LSE en peniques GBX, .JO, .TA): las velas no traen
    // divisa propia; solo hay fallback si el maestro ya declara la subunidad
    // (la misma divisa que rotula el gráfico). Con la unidad grande (GBP en un
    // .L) la escala sería ambigua (x100): sin fallback.
    const fallbackCurrency = chartFallbackCurrency({ ticker: snapshot.ticker, symbol, exchange: snapshot.exchange, currency: snapshot.currency, candleCurrency: snapshot.historyCurrency });
    const useFallback = !showPrice && (slow || settled) && fallbackPrice != null && isValidCurrencyCode(fallbackCurrency);
    // La vela de hoy puede ser parcial (sesión abierta): solo es «cierre» si su
    // mercado ya cerró (huso y hora de cierre del propio listado); si no, se
    // rotula «Última vela».
    const lastIsClose = last != null && isClosedCandle(last.date, { symbol: symbol ?? snapshot.ticker, currency: snapshot.currency });
    const loading = !settled && !useFallback;
    // Con fallback, la divisa es la del listado; con cotización real, la suya.
    const currency: string = (useFallback ? fallbackCurrency : quoteCurrency) ?? '';
    const hasDatedMetrics = !!quote?.metrics_timestamp && !!quote.metrics_session;
    return (
        <div className="flex w-full flex-col gap-4" data-testid="company-header-quote">
            <div>
                <p className="text-[11px] uppercase tracking-wide text-gray-500">{showPrice ? label : useFallback ? `${lastIsClose ? 'Último cierre del gráfico' : 'Última vela del gráfico (puede ser parcial)'} · ${formatMarketDate(last!.date)}` : loading ? '\u00a0' : NA}</p>
                <div className="text-4xl font-semibold tracking-tight text-gray-100 sm:text-5xl" aria-busy={loading || undefined}>
                    {showPrice ? headerMoney(quote!.price, currency) : useFallback ? headerMoney(fallbackPrice, fallbackCurrency!) : loading ? (
                        <>
                            <span className="sr-only">Cargando precio…</span>
                            <span aria-hidden="true" className="inline-block h-10 w-44 animate-pulse rounded bg-gray-800 align-middle sm:h-12" />
                        </>
                    ) : NA}
                </div>
                {showPrice && quote && quote.session !== 'cerrado' && (quote.change != null || quote.change_percent != null) && signBase !== 0 ? (
                    <div className={`mt-2 inline-flex w-fit items-center rounded-full px-2.5 py-1 text-sm font-medium ${signBase > 0 ? 'bg-emerald-500/10 text-emerald-300' : signBase < 0 ? 'bg-red-500/10 text-red-300' : 'bg-gray-800 text-gray-300'}`}>
                        {[
                            quote.change != null ? headerChangeMoney(quote.change, currency) : null,
                            quote.change_percent != null ? formatPercent(quote.change_percent, { fromRatio: false, digits: 2, signDisplay: 'always' }) : null,
                        ].filter(Boolean).join(' · ')}
                    </div>
                ) : null}
                {showPrice && quote && quote.session === 'cerrado' && quote.close_change_percent != null && quote.close_change_date && quote.close_change_previous_date ? (
                    <div data-testid="close-change">
                        <div className={`mt-2 inline-flex w-fit items-center rounded-full px-2.5 py-1 text-sm font-medium ${quote.close_change_percent > 0 ? 'bg-emerald-500/10 text-emerald-300' : quote.close_change_percent < 0 ? 'bg-red-500/10 text-red-300' : 'bg-gray-800 text-gray-300'}`}>
                            {[
                                quote.close_change != null ? headerChangeMoney(quote.close_change, currency) : null,
                                formatPercent(quote.close_change_percent, { fromRatio: false, digits: 2, signDisplay: 'always' }),
                            ].filter(Boolean).join(' · ')}
                        </div>
                        <p className="mt-1 text-xs text-gray-500">Último cierre vs anterior · {quoteSessionDate(quote.close_change_date)} vs {quoteSessionDate(quote.close_change_previous_date)}</p>
                    </div>
                ) : null}
                {useFallback ? <p className="mt-1 text-xs text-gray-500">Cotización en vivo no disponible ahora{snapshot.historySource ? ` · ${snapshot.historySource}` : ''}</p> : null}
                {showPrice ? <p className="mt-1 text-xs text-gray-500">{quote!.source} · {quoteTime(quote!.timestamp)} (Madrid)</p> : null}
                <details className="mt-1 text-gray-500" data-testid="quote-detail">
                    <summary className="inline-flex min-h-[44px] cursor-pointer items-center text-xs text-gray-400 sm:min-h-0">Más detalle</summary>
                    <div className="mt-1 space-y-1">
                {duplicatedClose || useFallback ? null : (
                    <p className="text-xs text-gray-500">
                        Cierre regular: {loading ? <span aria-hidden="true" className="inline-block h-3 w-24 animate-pulse rounded bg-gray-800 align-middle" /> : showPrice && quote?.regular_close != null && (quote.regular_close_timestamp || quote.regular_close_date) ? `${headerMoney(quote.regular_close, currency)} · ${quote.regular_close_timestamp ? `${quoteDate(quote.regular_close_timestamp)} · ${quoteTime(quote.regular_close_timestamp)}` : quoteSessionDate(quote.regular_close_date)}` : NA}
                    </p>
                )}
                {hasDatedMetrics ? <p className="text-xs text-gray-500">Sesión regular del {formatMarketDate(quote!.metrics_session)} · {quoteTime(quote!.metrics_timestamp)} (Madrid)</p> : null}
                    </div>
                </details>
            </div>
            <div className="min-w-0 max-w-full">
                <dl className="grid min-w-0 grid-cols-2 gap-x-3 border-y border-gray-800 sm:grid-cols-4 sm:gap-x-0 sm:divide-x sm:divide-gray-800" data-testid="company-metric-strip">
                    {(useFallback ? [
                        ['Apertura', last?.open ?? null],
                        ['Máximo', last?.high ?? null],
                        ['Mínimo', last?.low ?? null],
                        ['Cierre anterior', prev?.close ?? null],
                    ] : [
                        ['Apertura', hasDatedMetrics ? quote!.open : null],
                        ['Máximo', hasDatedMetrics ? quote!.high : null],
                        ['Mínimo', hasDatedMetrics ? quote!.low : null],
                        ['Cierre anterior', quote?.previous_close_timestamp || quote?.previous_close_date ? quote.previous_close : null],
                    ]).map(([metricLabel, value]) => (
                        <div className="min-w-0 py-3 sm:px-3 sm:first:pl-0" key={String(metricLabel)}>
                            <dt className="text-xs text-gray-500">{metricLabel}</dt>
                            <dd className="mt-1 break-words text-sm font-medium text-gray-200">{loading ? <span aria-hidden="true" className="inline-block h-4 w-16 animate-pulse rounded bg-gray-800 align-middle" /> : value == null || !isValidCurrencyCode(currency) ? NA : headerMoney(value as number, currency)}</dd>
                            {useFallback && metricLabel === 'Cierre anterior' && prev ? <dd className="break-words text-[11px] text-gray-500">{formatMarketDate(prev.date)}</dd> : null}
                            {!useFallback && metricLabel === 'Cierre anterior' && (quote?.previous_close_timestamp || quote?.previous_close_date) ? <dd className="break-words text-[11px] text-gray-500">{quote.previous_close_timestamp ? `${quoteDate(quote.previous_close_timestamp)} · ${quoteTime(quote.previous_close_timestamp)}` : quoteSessionDate(quote.previous_close_date)}</dd> : null}
                        </div>
                    ))}
                </dl>
            </div>
            <CompanyTechnicalWorkspace snapshot={snapshot} />
        </div>
    );
}
