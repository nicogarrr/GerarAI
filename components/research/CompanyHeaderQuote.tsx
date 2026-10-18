'use client';

import { useEffect, useState } from 'react';
import { NA, formatMoney, formatNumber, formatPercent, isValidCurrencyCode } from '@/lib/format';
import { extendedQuoteLabel, quoteDate, quoteTime, quoteSessionDate, type ExtendedQuote } from '@/lib/market/extended-quote';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { CompanyTechnicalWorkspace } from './CompanyTechnicalWorkspace';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';

/** USD prices follow the user's English style; other listings keep their own currency. */
function headerMoney(value: number | null | undefined, currency: string): string {
    if (currency === 'USD' && value != null && Number.isFinite(value)) {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
    }
    return formatMoney(value, currency);
}

/** One timestamped Yahoo payload supplies the price and all header metrics. */
export function CompanyHeaderQuote({ snapshot }: { snapshot: CompanyMarketSnapshot }) {
    const [quote, setQuote] = useState<ExtendedQuote | null>(null);
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
        setQuote(null);
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
                if (!disposed) setQuote(value?.status !== 'unavailable' ? value : null);
            } catch {
                if (!disposed) setQuote(null); // No stale-on-error price.
            } finally { inFlight = false; }
        };
        void refresh(true);
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
    const currency = quote?.currency ?? null;
    const label = extendedQuoteLabel(quote);
    const showPrice = label !== NA && quote?.price != null && isValidCurrencyCode(currency);
    const signBase = quote?.change ?? quote?.change_percent ?? 0;
    // «Cierre regular» repite «Cierre anterior» cuando ambos son el mismo dato: se muestra una sola vez.
    const duplicatedClose = quote?.regular_close != null && quote.regular_close === quote.previous_close;
    const hasDatedMetrics = !!quote?.metrics_timestamp && !!quote.metrics_session;
    return (
        <div className="flex w-full flex-col gap-4" data-testid="company-header-quote">
            <div>
                <p className="text-[11px] uppercase tracking-wide text-gray-500">{showPrice ? label : NA}</p>
                <div className="text-4xl font-semibold tracking-tight text-gray-100 sm:text-5xl">
                    {showPrice ? headerMoney(quote!.price, currency) : NA}
                </div>
                {showPrice && quote && quote.session !== 'cerrado' && (quote.change != null || quote.change_percent != null) ? (
                    <div className={`mt-2 inline-flex w-fit items-center rounded-full px-2.5 py-1 text-sm font-medium ${signBase > 0 ? 'bg-emerald-500/10 text-emerald-300' : signBase < 0 ? 'bg-red-500/10 text-red-300' : 'bg-gray-800 text-gray-300'}`}>
                        {[
                            quote.change != null ? (currency === 'USD' ? new Intl.NumberFormat('en-US', {signDisplay:'always', minimumFractionDigits:2, maximumFractionDigits:2}).format(quote.change) : formatNumber(quote.change, { signDisplay: 'always', maximumFractionDigits: 2 })) : null,
                            quote.change_percent != null ? (currency === 'USD' ? `${new Intl.NumberFormat('en-US', {signDisplay:'always', minimumFractionDigits:2, maximumFractionDigits:2}).format(quote.change_percent)}%` : formatPercent(quote.change_percent, { fromRatio: false, digits: 2, signDisplay: 'always' })) : null,
                        ].filter(Boolean).join(' · ')}
                    </div>
                ) : null}
                {duplicatedClose ? null : (
                    <p className="mt-2 text-xs text-gray-500">
                        Cierre regular: {showPrice && quote?.regular_close != null && (quote.regular_close_timestamp || quote.regular_close_date) ? `${headerMoney(quote.regular_close, currency)} · ${quote.regular_close_timestamp ? `${quoteDate(quote.regular_close_timestamp)} · ${quoteTime(quote.regular_close_timestamp)}` : quoteSessionDate(quote.regular_close_date)}` : NA}
                    </p>
                )}
                {showPrice ? <p className="mt-1 text-xs text-gray-500">{quote!.source} · {quoteTime(quote!.timestamp)} (Madrid)</p> : null}
            </div>
            <div className="min-w-0 max-w-full">
                <dl className="grid min-w-0 grid-cols-2 gap-x-3 border-y border-gray-800 sm:grid-cols-4 sm:gap-x-0 sm:divide-x sm:divide-gray-800" data-testid="company-metric-strip">
                    {[
                        ['Apertura', hasDatedMetrics ? quote!.open : null],
                        ['Máximo', hasDatedMetrics ? quote!.high : null],
                        ['Mínimo', hasDatedMetrics ? quote!.low : null],
                        ['Cierre anterior', quote?.previous_close_timestamp || quote?.previous_close_date ? quote.previous_close : null],
                    ].map(([metricLabel, value]) => (
                        <div className="min-w-0 py-3 sm:px-3 sm:first:pl-0" key={String(metricLabel)}>
                            <dt className="text-xs text-gray-500">{metricLabel}</dt>
                            <dd className="mt-1 break-words text-sm font-medium text-gray-200">{value == null || !isValidCurrencyCode(currency) ? NA : headerMoney(value as number, currency)}</dd>
                            {metricLabel === 'Cierre anterior' && (quote?.previous_close_timestamp || quote?.previous_close_date) ? <p className="break-words text-[11px] text-gray-500">{quote.previous_close_timestamp ? `${quoteDate(quote.previous_close_timestamp)} · ${quoteTime(quote.previous_close_timestamp)}` : quoteSessionDate(quote.previous_close_date)}</p> : null}
                        </div>
                    ))}
                </dl>
                {hasDatedMetrics ? <p className="mt-2 text-xs text-gray-500">Sesión regular del {quote!.metrics_session} · {quoteTime(quote!.metrics_timestamp)} (Madrid)</p> : null}
            </div>
            <CompanyTechnicalWorkspace snapshot={snapshot} />
        </div>
    );
}
