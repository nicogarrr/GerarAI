'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCcw } from 'lucide-react';

import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';
import {
    formatQuoteAge,
    formatQuoteChange,
    formatQuoteChangePercent,
    localizeInstrumentType,
    quoteAgeSeconds,
    resolveGroupRows,
    type LiveMarketsResult,
    type LiveQuote,
    type LiveQuoteKind,
    type LiveQuoteSpec,
} from '@/lib/market/live-quotes';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';

const POLL_MS = 60_000;

const TABS: { key: LiveQuoteKind; label: string; note: string }[] = [
    { key: 'indice', label: 'Índices', note: 'Nivel del índice en puntos.' },
    { key: 'futuro', label: 'Futuros', note: 'Futuros sobre índices USA, en puntos.' },
    {
        key: 'accion',
        label: 'Acciones ES',
        note: 'Selección de valores del IBEX 35. No es un ranking por volumen: sin una fuente gratuita de «más negociadas» no sostenemos esa etiqueta.',
    },
    { key: 'materia', label: 'Materias primas', note: 'Futuros de referencia en dólares.' },
    { key: 'divisa', label: 'Divisas', note: 'Tipo de cambio entre divisas.' },
];

const priceFormatter = (unit: LiveQuote['unit'], decimals: number) =>
    new Intl.NumberFormat('es-ES', {
        style: unit === 'index' || unit === 'cruz' ? 'decimal' : 'currency',
        currency: unit === 'index' || unit === 'cruz' ? undefined : unit,
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });

const timeFormatter = new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
});

function formatPrice(quote: LiveQuote): string {
    return priceFormatter(quote.unit, quote.decimals).format(quote.price);
}

function sessionLabel(session: LiveQuote['session']): string | null {
    if (session === 'pre') return 'premercado';
    if (session === 'post') return 'postmercado';
    return null;
}

function identityLine(quote: LiveQuote): string {
    const parts = [quote.symbol];
    if (quote.exchangeName) parts.push(quote.exchangeName);
    const kindLabel = localizeInstrumentType(quote.instrumentType);
    if (kindLabel) parts.push(kindLabel);
    return parts.join(' · ');
}

function QuoteRow({ spec, quote, fetchedAt }: { spec: LiveQuoteSpec; quote: LiveQuote | null; fetchedAt: number }) {
    if (!quote) {
        // El proveedor fallo para ESTE instrumento: la fila conserva su
        // identidad (nombre + simbolo) y solo el dato queda N/D.
        return (
            <tr className="border-b border-gray-800/60">
                <td className="py-2.5 pr-2">
                    <div className="text-gray-100">{spec.name}</div>
                    <div className="text-xs text-gray-500">{spec.symbol}</div>
                </td>
                <td className="py-2.5 px-2 text-right text-gray-500 whitespace-nowrap" colSpan={2}>N/D</td>
            </tr>
        );
    }
    const changeClass = quote.changePercent === null ? 'text-gray-500' : quote.changePercent >= 0 ? 'text-good' : 'text-bad';
    const age = quoteAgeSeconds(fetchedAt, quote.timestamp);
    const session = sessionLabel(quote.session);
    return (
        <tr className="border-b border-gray-800/60">
            <td className="py-2.5 pr-2">
                <div className="text-gray-100">{quote.name}</div>
                <div className="text-xs text-gray-500">{identityLine(quote)}</div>
                <div className="text-xs text-gray-500">
                    {quote.timestamp ? timeFormatter.format(new Date(quote.timestamp * 1000)) : 'sin hora'}
                    {/* La frase de edad es una unidad inseparable: si la linea
                        no cabe (390 + autosizing), salta entera a la 2ª linea
                        en vez de dejar "min" huerfano. No se recorta dato. */}
                    {age !== null ? (
                        <>
                            {' · '}
                            <span className="whitespace-nowrap">{formatQuoteAge(age)}</span>
                        </>
                    ) : ''}
                    {session ? ` · ${session}` : ''}
                </div>
            </td>
            <td className="py-2.5 px-2 text-right font-medium text-gray-100 whitespace-nowrap">{formatPrice(quote)}</td>
            <td className={`py-2.5 pl-2 text-right whitespace-nowrap ${changeClass}`}>
                {quote.change === null || quote.changePercent === null ? (
                    'N/D'
                ) : (
                    <>
                        <div>{formatQuoteChange(quote.change, quote.decimals)}</div>
                        <div className="text-xs">({formatQuoteChangePercent(quote.changePercent)}%)</div>
                    </>
                )}
            </td>
        </tr>
    );
}

export function LiveMarketsPanel({ initial }: { initial: LiveMarketsResult | null }) {
    const [data, setData] = useState<LiveMarketsResult | null>(initial);
    const [refreshing, setRefreshing] = useState(false);
    const [failed, setFailed] = useState(false);

    const refresh = useCallback(async () => {
        setRefreshing(true);
        try {
            const next = await getLiveMarkets();
            setData(next);
            setFailed(false);
        } catch {
            // Conservamos lo ultimo bueno; la antigüedad por fila sigue siendo honesta.
            setFailed(true);
        } finally {
            setRefreshing(false);
        }
    }, []);

    useEffect(() => {
        const timer = setInterval(refresh, POLL_MS);
        return () => clearInterval(timer);
    }, [refresh]);

    return (
        <div className="mt-4">
            <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
                <span>
                    {data
                        ? `Actualizado a las ${timeFormatter.format(new Date(data.fetchedAt))} (hora de Madrid)`
                        : 'Sin datos todavía'}
                    {failed ? ' · la última actualización falló; se reintenta cada minuto' : ''}
                </span>
                <Button className="min-w-11" variant="ghost" size="sm" onClick={refresh} disabled={refreshing} aria-label="Actualizar ahora">
                    <RefreshCcw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                </Button>
            </div>
            <Tabs defaultValue="indice" className="mt-3">
                {/* h-auto: con flex-wrap la lista crece a 2 filas en móvil; con la
                    altura fija base (h-9) la 2ª fila se montaba sobre el texto
                    siguiente y esas tabs no respondían al toque (21-oct-2026). */}
                <TabsList className="h-auto flex-wrap gap-y-1">
                    {TABS.map((tab) => (
                        <TabsTrigger className="min-h-11" key={tab.key} value={tab.key}>{tab.label}</TabsTrigger>
                    ))}
                </TabsList>
                {TABS.map((tab) => {
                    const group = data?.groups.find((g) => g.key === tab.key) ?? null;
                    return (
                        <TabsContent key={tab.key} value={tab.key}>
                            <p className="mb-2 text-xs text-gray-500">{tab.note}</p>
                            {group ? (
                                <table className="w-full text-sm">
                                    <tbody>
                                        {resolveGroupRows(tab.key, group.quotes).map(({ spec, quote }) => (
                                            <QuoteRow key={spec.symbol} spec={spec} quote={quote} fetchedAt={data?.fetchedAt ?? 0} />
                                        ))}
                                    </tbody>
                                </table>
                            ) : (
                                <p className="py-6 text-center text-sm text-gray-500">
                                    No hay datos disponibles ahora. Se reintenta cada minuto.
                                </p>
                            )}
                        </TabsContent>
                    );
                })}
            </Tabs>
            <p className="mt-4 text-xs leading-5 text-gray-500">
                Fuente: Yahoo Finance. Cada fila muestra la hora que informa el proveedor y su antigüedad
                al consultar la fuente (hora de Madrid); el panel se actualiza cada minuto. No son datos
                oficiales de mercado ni sirven para operar con garantías.
            </p>
        </div>
    );
}
