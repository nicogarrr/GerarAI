'use client';

import { useEffect, useState } from 'react';

import { getExtendedQuote } from '@/lib/actions/watchlist.actions';
import { extendedQuoteLabel, type ExtendedQuote } from '@/lib/market/extended-quote';
import { formatNumber, formatPercent, formatPrice } from '@/lib/format';

/**
 * Línea pre/post-mercado (decorativa). Antes el render de servidor esperaba
 * la cotización extendida de CADA símbolo con un tope de 700 ms
 * (EXTENDED_QUOTE_BUDGET_MS): toda carga en frío de /watchlist pagaba ese
 * tope aunque la línea es secundaria. Ahora se pide en cliente tras el
 * primer pintado; hasta que responde no se pinta nada — igual que cuando la
 * lectura falla — nunca un dato inventado.
 */
export default function ExtendedHoursLine({ symbol, currency }: { symbol: string; currency: string | null }) {
    const [quote, setQuote] = useState<ExtendedQuote | null>(null);

    useEffect(() => {
        let cancelled = false;
        getExtendedQuote(symbol)
            .then((data) => {
                if (!cancelled) setQuote(data);
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [symbol]);

    if (!quote || quote.price == null || (quote.price_session !== 'pre' && quote.price_session !== 'post')) return null;
    const priceText = currency ? formatPrice(quote.price, currency) : formatNumber(quote.price);
    const changeText =
        typeof quote.change_percent === 'number' && Number.isFinite(quote.change_percent)
            ? ` (${formatPercent(quote.change_percent, { fromRatio: false, digits: 2, signDisplay: 'always' })})`
            : '';
    return (
        <div className="text-[10px] font-normal text-gray-500">
            {extendedQuoteLabel(quote)}: {priceText}
            {changeText}
        </div>
    );
}
