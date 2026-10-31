'use client';

import { useEffect, useState } from 'react';

import { getExtendedQuotes } from '@/lib/actions/watchlist.actions';
import { batchedSymbol } from '@/lib/cache/batch-symbols';
import { requestCache } from '@/lib/cache/requestCache';
import { extendedQuoteLabel, type ExtendedQuote } from '@/lib/market/extended-quote';
import { formatNumber, formatPercent, formatPrice } from '@/lib/format';

/**
 * Línea pre/post-mercado (decorativa). Antes el render de servidor esperaba
 * la cotización extendida de CADA símbolo con un tope de 700 ms
 * (EXTENDED_QUOTE_BUDGET_MS): toda carga en frío de /watchlist pagaba ese
 * tope aunque la línea es secundaria. Ahora se pide en cliente tras el
 * primer pintado; hasta que responde no se pinta nada — igual que cuando la
 * lectura falla — nunca un dato inventado.
 *
 * /watchlist y /portfolio montan la línea DOS veces por fila (tarjetas
 * móviles y tabla de escritorio van las dos en el DOM): pasaba a ser 2
 * llamadas idénticas por símbolo. requestCache deduplica las concurrentes y
 * guarda el dato EXTENDED_QUOTE_TTL_S: cada símbolo se pide 1 vez por
 * minuto aunque cambie la paginación.
 */
const EXTENDED_QUOTE_TTL_S = 60;
export default function ExtendedHoursLine({
    symbol,
    currency,
    as: Tag = 'div',
}: {
    symbol: string;
    currency: string | null;
    // Dentro de una ficha <dl> la linea es un <dd>: un <div> suelto en el grupo
    // dt/dd rompe la lista de definiciones para el lector de pantalla.
    as?: 'div' | 'dd';
}) {
    const [quote, setQuote] = useState<ExtendedQuote | null>(null);

    useEffect(() => {
        let cancelled = false;
        requestCache.get(`extended-quote:${symbol.toUpperCase()}`, () => batchedSymbol('extended-quote', symbol.toUpperCase(), (symbols) => getExtendedQuotes(symbols)), EXTENDED_QUOTE_TTL_S)
            .then((data) => {
                if (!cancelled) setQuote(data);
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [symbol]);

    if (!quote || quote.price == null || (quote.price_session !== 'pre' && quote.price_session !== 'post')) return null;
    // El ticker pelado puede resolver al gemelo US (ASML -> ADR en USD) mientras
    // la fila es el listado europeo en EUR: otra divisa = otro valor, no se pinta
    // un precio USD con simbolo de euro.
    if (quote.currency && currency && quote.currency.toUpperCase() !== currency.toUpperCase()) return null;
    const shownCurrency = currency ?? quote.currency ?? null;
    const priceText = shownCurrency ? formatPrice(quote.price, shownCurrency) : formatNumber(quote.price);
    const changeText =
        typeof quote.change_percent === 'number' && Number.isFinite(quote.change_percent)
            ? ` (${formatPercent(quote.change_percent, { fromRatio: false, digits: 2, signDisplay: 'always' })})`
            : '';
    return (
        <Tag className="text-[10px] font-normal text-gray-500">
            {extendedQuoteLabel(quote)}: {priceText}
            {changeText}
        </Tag>
    );
}
