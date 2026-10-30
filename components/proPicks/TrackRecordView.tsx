'use client';

import { useEffect, useState } from 'react';
import { History, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { formatMarketDate, formatPercent } from '@/lib/format';
import { getTrackRecord, type TrackRecordPick, type TrackRecordResponse } from '@/lib/actions/propicks-track-record.actions';

const signedClass = (v: number) => (v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-gray-300');

function pct(v: number | null): string {
    if (v === null || v === undefined) return '—';
    return formatPercent(v, { digits: 1, signDisplay: 'always' });
}

/** Celda % con la cifra de SPY de la misma ventana debajo. */
function PctWithSpy({ value, spy }: { value: number | null; spy: number | null }) {
    return (
        <div className="text-right">
            <span className={value === null ? 'text-gray-500' : signedClass(value)}>{pct(value)}</span>
            <span className="block text-xs text-gray-500">SPY {pct(spy)}</span>
        </div>
    );
}

function PickRow({ pick }: { pick: TrackRecordPick }) {
    const salio = pick.status === 'salio';
    return (
        <tr className="border-b border-gray-800 text-sm text-gray-300">
            <th scope="row" className="py-2 pr-3 text-left font-medium text-gray-100">
                {pick.ticker}
                <span className="block max-w-[10rem] truncate text-xs font-normal text-gray-500">{pick.name}</span>
            </th>
            <td className="py-2 pr-3 text-left">
                {pick.entry_month}
                {pick.entry_price !== null && (
                    <span className="block text-xs text-gray-500">
                        {pick.entry_price} {pick.currency ?? ''} · {formatMarketDate(pick.entry_price_date)}
                    </span>
                )}
            </td>
            <td className="py-2 pr-3 text-left">
                {salio ? (
                    <>
                        {pick.exit_month}
                        <span className="block text-xs text-gray-500">
                            {pick.exit_price !== null ? `${pick.exit_price} · ${formatMarketDate(pick.exit_price_date)}` : 'sin precio de salida'}
                        </span>
                    </>
                ) : pick.current_stale ? (
                    <span className="text-gray-500">
                        sin dato actual
                        <span className="block text-xs">último {formatMarketDate(pick.current_price_date)}</span>
                    </span>
                ) : (
                    <>
                        activo
                        {pick.current_price !== null && (
                            <span className="block text-xs text-gray-500">
                                {pick.current_price} · {formatMarketDate(pick.current_price_date)}
                            </span>
                        )}
                    </>
                )}
            </td>
            <td className="py-2 pr-3">
                {salio ? (
                    <PctWithSpy value={pick.exit_pct} spy={pick.spy_pct_exit} />
                ) : (
                    <PctWithSpy value={pick.pct_since_entry} spy={pick.spy_pct_since_entry} />
                )}
            </td>
            <td className="py-2">
                <PctWithSpy value={pick.pct_90d} spy={pick.spy_pct_90d} />
                {pick.horizon_date && pick.pct_90d === null && (
                    <span className="block text-right text-xs text-gray-500">pendiente ({formatMarketDate(pick.horizon_date)})</span>
                )}
            </td>
        </tr>
    );
}

export default function TrackRecordView() {
    const [data, setData] = useState<TrackRecordResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const load = async () => {
        setLoading(true);
        setError(null);
        const result = await getTrackRecord();
        if ('error' in result) setError(result.error);
        else setData(result);
        setLoading(false);
    };

    useEffect(() => {
        // Carga inicial tras montar: el setState de load no es síncrono en el efecto.
        queueMicrotask(() => void load());
    }, []);

    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h4 className="flex items-center gap-2 text-base font-bold text-gray-100">
                        <History aria-hidden="true" className="h-4 w-4 text-teal-400" />
                        Ganadores anteriores
                        {data && data.snapshots_count > 0 && (
                            <span className="text-sm font-normal text-gray-400">· {data.history_label}</span>
                        )}
                    </h4>
                    <p className="mt-1 max-w-2xl text-xs leading-5 text-gray-500">
                        Selecciones reales del embudo congeladas cada mes (snapshots point-in-time). Cada cifra
                        lleva su fecha; SPY es la referencia en la misma ventana. Sin agregados mientras el
                        historial sea corto: unos pocos meses no dicen nada.
                    </p>
                </div>
                <Button onClick={load} disabled={loading} variant="outline" className="h-11 gap-2">
                    {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="h-4 w-4" />}
                    Actualizar
                </Button>
            </div>

            {error && <p className="mt-4 rounded-lg border border-red-700 bg-red-900/20 p-3 text-sm text-red-400">{error}</p>}

            {data && data.snapshots_count === 0 && !error && (
                <div className="mt-4 rounded-lg border border-gray-700 bg-gray-900/40 p-6 text-center">
                    <p className="font-medium text-gray-300">Aún no hay histórico</p>
                    <p className="mt-2 text-sm text-gray-500">
                        El primer snapshot mensual se congela el día 1 de cada mes tras el cierre de EE.&nbsp;UU.
                        Cuando exista al menos uno, aquí aparecerá cada selección con su precio de entrada, su
                        evolución y el resultado a 90 días frente a SPY.
                    </p>
                </div>
            )}

            {data && data.picks.length > 0 && (
                <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[640px]">
                        <caption className="sr-only">
                            Track record de selecciones ProPicks: entrada, salida o estado actual, retorno desde
                            la entrada y retorno a 90 días, cada uno frente a SPY en la misma ventana
                        </caption>
                        <thead>
                            <tr className="border-b border-gray-700 text-xs uppercase tracking-wide text-gray-500">
                                <th className="py-2 pr-3 text-left" scope="col">Valor</th>
                                <th className="py-2 pr-3 text-left" scope="col">Entrada</th>
                                <th className="py-2 pr-3 text-left" scope="col">Salida / actual</th>
                                <th className="py-2 pr-3 text-right" scope="col">Desde entrada</th>
                                <th className="py-2 text-right" scope="col">A {data.horizon_days} días</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.picks.map((pick) => (
                                <PickRow key={`${pick.ticker}-${pick.entry_month}`} pick={pick} />
                            ))}
                        </tbody>
                    </table>
                    {data.spy.available && data.spy.latest_date && (
                        <p className="mt-2 text-xs text-gray-500">
                            SPY ({data.spy.source}) con datos hasta {formatMarketDate(data.spy.latest_date)}.
                        </p>
                    )}
                    {!data.spy.available && (
                        <p className="mt-2 text-xs text-gray-500">Serie de SPY sin datos todavía: las columnas vs SPY saldrán cuando se ingiera.</p>
                    )}
                </div>
            )}
        </Card>
    );
}
