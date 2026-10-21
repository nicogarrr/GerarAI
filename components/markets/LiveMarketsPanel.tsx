'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCcw } from 'lucide-react';

import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';
import type { LiveMarketsResult, LiveQuote, LiveQuoteKind } from '@/lib/market/live-quotes';
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

const priceFormatter = (unit: LiveQuote['unit']) =>
    new Intl.NumberFormat('es-ES', {
        style: unit === 'index' || unit === 'cruz' ? 'decimal' : 'currency',
        currency: unit === 'index' || unit === 'cruz' ? undefined : unit,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });

const changeFormatter = new Intl.NumberFormat('es-ES', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: 'always',
});

const timeFormatter = new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
});

function formatPrice(quote: LiveQuote): string {
    return priceFormatter(quote.unit).format(quote.price);
}

function QuoteRow({ quote }: { quote: LiveQuote | null }) {
    if (!quote) {
        return (
            <tr className="border-b border-gray-800/60">
                <td className="py-2.5 pr-2 text-gray-500" colSpan={3}>N/D</td>
            </tr>
        );
    }
    const changeClass = quote.changePercent === null ? 'text-gray-500' : quote.changePercent >= 0 ? 'text-teal-300' : 'text-red-400';
    return (
        <tr className="border-b border-gray-800/60">
            <td className="py-2.5 pr-2">
                <div className="text-gray-100">{quote.name}</div>
                <div className="text-xs text-gray-500">
                    {quote.timestamp ? timeFormatter.format(new Date(quote.timestamp * 1000)) : 'sin hora'}
                </div>
            </td>
            <td className="py-2.5 px-2 text-right font-medium text-gray-100 whitespace-nowrap">{formatPrice(quote)}</td>
            <td className={`py-2.5 pl-2 text-right whitespace-nowrap ${changeClass}`}>
                {quote.change === null || quote.changePercent === null ? (
                    'N/D'
                ) : (
                    <>
                        <div>{changeFormatter.format(quote.change)}</div>
                        <div className="text-xs">({changeFormatter.format(quote.changePercent)}%)</div>
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
            // Conservamos lo ultimo bueno; el aviso dice que puede ir con retraso extra.
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
                <Button variant="ghost" size="sm" onClick={refresh} disabled={refreshing} aria-label="Actualizar ahora">
                    <RefreshCcw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                </Button>
            </div>
            <Tabs defaultValue="indice" className="mt-3">
                <TabsList className="flex-wrap">
                    {TABS.map((tab) => (
                        <TabsTrigger key={tab.key} value={tab.key}>{tab.label}</TabsTrigger>
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
                                        {group.quotes.map((quote, i) => (
                                            <QuoteRow key={i} quote={quote} />
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
                Fuente: Yahoo Finance. Las acciones suelen llevar unos 15 minutos de retraso; índices, futuros y
                divisas van casi en tiempo. La hora de cada cotización es la que informa el proveedor (hora de
                Madrid). No son datos oficiales de mercado ni sirven para operar con garantías.
            </p>
        </div>
    );
}
