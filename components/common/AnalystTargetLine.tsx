'use client';

import { useEffect, useState } from 'react';

import { getListingAnalystTargets, type ListingAnalystTargets } from '@/lib/actions/analyst-targets.actions';
import { requestCache } from '@/lib/cache/requestCache';
import { formatNumber, formatPercent, formatPrice, NA } from '@/lib/format';
import { convertWithPortfolioFx, unconvertedTargetLabel, type TargetFxRate } from '@/lib/analyst-target-currency';

/**
 * Consenso de precios objetivo de analistas para las listas (watchlist y
 * cartera): la media del consenso y el recorrido contra el precio de la
 * fila. Fuente gratuita y no oficial (Yahoo Finance): se pide en cliente
 * tras el primer pintado para no frenar la carga, la fuente y la hora van
 * en el title, y sin dato se pinta N/D — nunca una cifra inventada.
 *
 * Divisa: la declarada por Yahoo para el listado consultado. Si difiere de
 * la de la fila (p. ej. ASML en EUR con objetivos del ADR en USD) y la página
 * pasa los tipos de cambio de la cartera, se convierte a la divisa de la fila
 * con la nota «(convertido de USD)» y entonces sí hay recorrido. Sin tipo de
 * cambio se muestra con SU divisa, etiquetada «(ADR, USD)», y sin recorrido:
 * nunca se mezclan divisas en una cifra o un % sin decirlo.
 * Si Yahoo no declara divisa, número pelado y sin recorrido.
 *
 * /watchlist y /portfolio montan la línea DOS veces por fila (tarjetas
 * móviles + tabla de escritorio, ambas en el DOM): eran 2 lecturas iguales
 * por símbolo tras el primer pintado. requestCache las deduplica y guarda
 * el consenso ANALYST_TARGETS_TTL_S (cambia a diario como mucho): 1 lectura
 * por símbolo y ventana aunque se pagine o se remonte la lista.
 */
const ANALYST_TARGETS_TTL_S = 300;
export default function AnalystTargetLine({
    symbol,
    quoteSymbol,
    currency,
    referencePrice,
    fxRates,
    baseCurrency,
}: {
    symbol: string;
    /** Listado real ya resuelto por la página; omitir para resolverlo aquí. */
    quoteSymbol?: string | null;
    currency: string | null;
    referencePrice: number | null;
    /** Tipos de la cartera (divisa base por unidad de divisa) para convertir el objetivo. */
    fxRates?: readonly TargetFxRate[] | null;
    baseCurrency?: string | null;
}) {
    const [settled, setSettled] = useState(false);
    const [data, setData] = useState<ListingAnalystTargets | null>(null);

    useEffect(() => {
        let cancelled = false;
        requestCache.get(
            `analyst-targets:${symbol.toUpperCase()}:${(quoteSymbol ?? '').toUpperCase()}`,
            () => getListingAnalystTargets(symbol, quoteSymbol),
            ANALYST_TARGETS_TTL_S,
        )
            .then((value) => {
                if (cancelled) return;
                setData(value);
                setSettled(true);
            })
            .catch(() => {
                if (!cancelled) setSettled(true);
            });
        return () => {
            cancelled = true;
        };
    }, [symbol, quoteSymbol]);

    if (!settled) {
        return (
            <span className="text-gray-600" role="status" aria-label={`Cargando precio objetivo de analistas de ${symbol}`}>
                …
            </span>
        );
    }
    if (!data || data.status !== 'available' || data.mean === null) {
        return (
            <span className="text-gray-500" title={data?.note ?? 'Sin precios objetivo por analista para este valor.'}>
                {NA}
            </span>
        );
    }
    const rowCurrency = currency ? currency.toUpperCase() : null;
    const currencyMismatch = data.currency !== null && rowCurrency !== null && data.currency !== rowCurrency;
    const sameCurrency = data.currency !== null && rowCurrency !== null && data.currency === rowCurrency;
    const converted =
        currencyMismatch && data.currency && rowCurrency
            ? convertWithPortfolioFx(data.mean, data.currency, rowCurrency, fxRates, baseCurrency)
            : null;
    const shownMean = sameCurrency ? data.mean : converted;
    const upside =
        shownMean !== null && referencePrice !== null && referencePrice > 0
            ? (shownMean / referencePrice - 1) * 100
            : null;
    const fetchedNote = data.fetchedAt
        ? ` · obtenido ${new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(data.fetchedAt * 1000))}`
        : '';
    const mismatchNote = !currencyMismatch
        ? ''
        : converted !== null
          ? ` · objetivos en ${data.currency} convertidos a ${rowCurrency} con el tipo de cambio de la cartera`
          : ` · objetivos en ${data.currency}, la fila cotiza en ${rowCurrency}: sin tipo de cambio, sin recorrido por no mezclar divisas`;
    const firmsNote = data.firms > 0 ? `${data.firms} ${data.firms === 1 ? 'firma' : 'firmas'} con objetivo en 12 meses` : 'solo consenso agregado, sin detalle por firma';
    const title = `${data.source} · ${firmsNote}${fetchedNote}${mismatchNote}`;
    return (
        <span title={title}>
            <span className="font-mono text-gray-200">
                {converted !== null && rowCurrency
                    ? formatPrice(converted, rowCurrency)
                    : data.currency
                      ? formatPrice(data.mean, data.currency)
                      : formatNumber(data.mean)}
            </span>
            {currencyMismatch && data.currency ? (
                <span className="ml-1 text-[10px] text-gray-500">
                    {converted !== null ? `(convertido de ${data.currency})` : unconvertedTargetLabel(data.currency)}
                </span>
            ) : null}
            {upside !== null ? (
                <span className={`ml-1 font-mono text-xs ${upside >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatPercent(upside, { fromRatio: false, digits: 1, signDisplay: 'always' })}
                </span>
            ) : null}
        </span>
    );
}
