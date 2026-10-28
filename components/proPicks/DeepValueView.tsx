'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { formatPercent } from '@/lib/format';
import { getDeepValue, type DeepValueItem, type DeepValueResult } from '@/lib/actions/propicks-deep-value.actions';

const PB_OPTIONS = [
    { value: 0.5, label: 'P/B ≤ 0,5' },
    { value: 1.0, label: 'P/B ≤ 1,0' },
    { value: 1.5, label: 'P/B ≤ 1,5' },
    { value: 2.0, label: 'P/B ≤ 2,0' },
];
const YIELD_OPTIONS = [
    { value: 0, label: 'Cualquier dividendo' },
    { value: 0.03, label: 'Dividendo ≥ 3 %' },
    { value: 0.05, label: 'Dividendo ≥ 5 %' },
    { value: 0.08, label: 'Dividendo ≥ 8 %' },
];

function formatPb(value: number): string {
    return `${value.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}x`;
}

function YieldCell({ item }: { item: DeepValueItem }) {
    if (item.dividend_yield === null) {
        return <span className="text-sm text-gray-500">N/D</span>;
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold text-gray-100">
                {formatPercent(item.dividend_yield)}
            </span>
            {item.desacuerdo_fuentes && item.finnhub_yield_indicated !== null && (
                <span className="inline-flex w-fit items-center gap-1 rounded border border-amber-600/60 bg-amber-900/20 px-1.5 py-0.5 text-xs text-amber-300">
                    <AlertTriangle aria-hidden="true" className="h-3 w-3" />
                    Fuentes en desacuerdo: Finnhub indica {formatPercent(item.finnhub_yield_indicated)}
                </span>
            )}
            {item.yield_extremo_revisar && (
                <span className="inline-flex w-fit items-center gap-1 rounded border border-amber-600/60 bg-amber-900/20 px-1.5 py-0.5 text-xs text-amber-300">
                    <AlertTriangle aria-hidden="true" className="h-3 w-3" />
                    Yield muy alto: revisar si es un dividendo especial
                </span>
            )}
        </div>
    );
}

export default function DeepValueView() {
    const [data, setData] = useState<DeepValueResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [pbMax, setPbMax] = useState(1.0);
    const [yieldMin, setYieldMin] = useState(0);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        const result = await getDeepValue(pbMax, yieldMin);
        if ('error' in result) setError(result.error);
        else setData(result);
        setLoading(false);
    }, [pbMax, yieldMin]);

    useEffect(() => {
        void load();
    }, [load]);

    const asOf = data?.resultados.find((row) => row.metric_as_of)?.metric_as_of ?? null;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-lg font-bold text-gray-100">Deep value</h3>
                <Button onClick={load} disabled={loading} variant="outline" className="h-11 gap-2">
                    {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="h-4 w-4" />}
                    Actualizar
                </Button>
            </div>

            {/* Rotulo honesto de la estrategia: deep value NO es el filtro de
                calidad; el texto llega del servidor en cada respuesta. */}
            <Card role="note" className="rounded-lg border border-teal-800/60 bg-teal-950/20 p-3 text-sm text-teal-200">
                {data?.rotulo ?? 'Estrategia Deep value: descuento a valor en libros y dividendo. No es el filtro de calidad ProPicks: acepta apalancamiento y ciclicidad que el embudo rechaza.'}
            </Card>

            <div className="flex flex-wrap gap-2">
                {PB_OPTIONS.map((option) => (
                    <Button
                        key={option.value}
                        variant={pbMax === option.value ? 'default' : 'outline'}
                        className="h-11"
                        aria-pressed={pbMax === option.value}
                        onClick={() => setPbMax(option.value)}
                    >
                        {option.label}
                    </Button>
                ))}
                {YIELD_OPTIONS.map((option) => (
                    <Button
                        key={option.value}
                        variant={yieldMin === option.value ? 'default' : 'outline'}
                        className="h-11"
                        aria-pressed={yieldMin === option.value}
                        onClick={() => setYieldMin(option.value)}
                    >
                        {option.label}
                    </Button>
                ))}
            </div>

            {error && (
                <Card className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-sm text-red-400">{error}</Card>
            )}

            {!error && data && data.resultados.length === 0 && (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 text-sm text-gray-400">
                    Ninguna empresa del universo pasa estos filtros con datos recientes. Las métricas de valoración se calculan cada noche tras el cierre; si acaban de desplegarse, la primera corrida aún no ha llegado.
                </Card>
            )}

            {asOf && (
                <p className="text-xs text-gray-500">Datos al {new Date(`${asOf}T00:00:00`).toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
                {data?.resultados.map((item) => (
                    <Card key={item.ticker} className="flex min-w-0 flex-col gap-2 rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                        <div className="flex items-baseline justify-between gap-2">
                            <div className="min-w-0">
                                <span className="font-bold text-teal-300">{item.ticker}</span>{' '}
                                <span className="truncate text-sm text-gray-300">{item.name}</span>
                            </div>
                            <span className="flex-none text-sm font-semibold text-gray-100">{item.score.toLocaleString('es-ES')} ptos</span>
                        </div>
                        {item.sector && <p className="text-xs text-gray-500">{item.sector} · {item.exchange}</p>}
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <p className="text-xs text-gray-500">P/B{item.pb_fiscal_year ? ` (libros FY${item.pb_fiscal_year})` : ''}</p>
                                <p className="text-sm font-semibold text-gray-100">{formatPb(item.price_to_book)}</p>
                                {item.pb_price_date && <p className="text-xs text-gray-500">precio al {item.pb_price_date}</p>}
                            </div>
                            <div>
                                <p className="text-xs text-gray-500">Dividendo TTM</p>
                                <YieldCell item={item} />
                            </div>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
}
