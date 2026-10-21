'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCcw } from 'lucide-react';

import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';
import type { LiveMarketsResult, LiveQuote, LiveQuoteKind } from '@/lib/market/live-quotes';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';

const POLL_MS = 60_000;

const TABS: { key: LiveQuoteKind; label: string; note: string }[] = [
    {
        key: 'indice',
        label: 'Índices',
        note: 'Nivel del índice de contado en puntos: un índice se calcula, no se negocia directamente.',
    },
    {
        key: 'futuro',
        label: 'Futuros',
        note: 'Contratos continuos que informa Yahoo; la fuente no indica el vencimiento concreto, así que no lo mostramos.',
    },
    {
        key: 'accion',
        label: 'Acciones ES',
        note: 'Selección de valores del IBEX 35. No es un ranking por volumen: sin una fuente gratuita de «más negociadas» no sostenemos esa etiqueta.',
    },
    {
        key: 'materia',
        label: 'Materias primas',
        note: 'Contratos continuos de referencia. Ojo a la unidad de cada fila: no todo son dólares genéricos (el cobre son USD/libra).',
    },
    { key: 'divisa', label: 'Divisas', note: 'Tipo de cambio spot entre divisas.' },
];

// Moneda: formato nativo de cada divisa (USD en en-US con '$', EUR en es-ES).
// Indices en puntos (decimal es-ES). Divisas con 4 decimales: un EUR/USD a
// 2 decimales mostraria cambios de "+0,00", que no aportan.
const priceFormatter = (unit: LiveQuote['unit']) => {
    if (unit === 'USD') return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (unit === 'EUR') return new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (unit === 'cruz') return new Intl.NumberFormat('es-ES', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
    return new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const changeFormatter = (unit: LiveQuote['unit']) =>
    new Intl.NumberFormat('es-ES', {
        minimumFractionDigits: unit === 'cruz' ? 4 : 2,
        maximumFractionDigits: unit === 'cruz' ? 4 : 2,
        signDisplay: 'always',
    });

const changePercentFormatter = new Intl.NumberFormat('es-ES', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: 'always',
});

// Fecha Y hora del dato: una hora suelta ("22:45") no dice si es de hoy o
// del cierre de ayer, y eso induce a error.
const timeFormatter = new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
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
                    {quote.timestamp
                        ? `dato: ${timeFormatter.format(new Date(quote.timestamp * 1000))}`
                        : 'sin fecha del dato'}
                </div>
            </td>
            <td className="py-2.5 px-2 text-right whitespace-nowrap">
                <div className="font-medium text-gray-100">{formatPrice(quote)}</div>
                <div className="text-xs text-gray-500">{quote.unitLabel}</div>
            </td>
            <td className={`py-2.5 pl-2 text-right whitespace-nowrap ${changeClass}`}>
                {quote.change === null || quote.changePercent === null ? (
                    'N/D'
                ) : (
                    <>
                        <div>{changeFormatter(quote.unit).format(quote.change)}</div>
                        <div className="text-xs">({changePercentFormatter.format(quote.changePercent)}%)</div>
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

    // Sondeo solo con la pestaña visible: 38 peticiones/minuto por pestaña
    // oculta es carga que nadie ve (y cold starts la multiplican).
    useEffect(() => {
        let timer: ReturnType<typeof setInterval> | null = null;
        const start = () => {
            if (timer === null) timer = setInterval(refresh, POLL_MS);
        };
        const stop = () => {
            if (timer !== null) clearInterval(timer);
            timer = null;
        };
        const onVisibility = () => {
            if (document.hidden) {
                stop();
            } else {
                start();
                void refresh();
            }
        };
        start();
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            stop();
            document.removeEventListener('visibilitychange', onVisibility);
        };
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
                <TabsList className="h-auto flex-wrap">
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
                Fuente: Yahoo Finance. Cada fila muestra la fecha y hora que el proveedor atribuye al dato;
                no es una promesa de tiempo real.{' '}
                <details className="mt-1">
                    <summary className="cursor-pointer text-gray-400">Condiciones y límites de la fuente</summary>
                    <span className="mt-1 block">
                        Endpoint público sin documentación oficial: no hay SLA ni confirmación de derechos de
                        redistribución; es un riesgo de viabilidad pendiente de resolver, no un proveedor
                        garantizado. El retraso exacto de cada mercado no lo informa la fuente. No son datos
                        oficiales de mercado ni sirven para operar con garantías.
                    </span>
                </details>
            </p>
        </div>
    );
}
