'use client';

import { Card } from '@/components/ui/card';
import { MethodologyDisclosure } from '@/components/ui/methodology-disclosure';
import { EmptyState } from '@/components/ui/empty-state';
import { BarChart3 } from 'lucide-react';
import { formatMarketDate, formatNumber, formatPercent } from '@/lib/format';
import type { WalkForwardBacktestResult } from '@/lib/actions/propicks-backtest.actions';

interface WalkForwardResultsProps {
    result: WalkForwardBacktestResult;
}

/** El backtest entrega porcentajes ya multiplicados por 100 (puntos, no ratio). */
const fmtPct = (v: number, digits = 2) =>
    formatPercent(v, { fromRatio: false, digits, signDisplay: 'always' });
const signedClass = (v: number) => (v > 0 ? 'text-green-400' : 'text-red-400');

function Metric({ label, value, footnote }: { label: string; value: string; footnote?: string }) {
    return (
        <div className="rounded-lg border border-gray-700/50 bg-gray-900/50 p-3">
            <div className="mb-1 text-xs text-gray-500">{label}</div>
            <div className="text-lg font-bold text-gray-100">{value}</div>
            {footnote && <div className="mt-1 text-[11px] text-gray-500">{footnote}</div>}
        </div>
    );
}

export default function WalkForwardResults({ result }: WalkForwardResultsProps) {
    const first = result.tablaMensual[0];
    const last = result.tablaMensual[result.tablaMensual.length - 1];

    // Sin meses no hay curva: los agregados del resultado serían todos 0 y se
    // leerían como un rendimiento medido de 0,00 %. Se dice qué falta en su
    // lugar (el motor descarta un corte cuando el símbolo no tiene 253 cierres
    // previos o no hay cierre de salida; ver runWalkForwardBacktest).
    if (result.tablaMensual.length === 0) {
        return (
            <Card className="w-full min-w-0 overflow-hidden rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-6">
                <div className="mb-4 flex items-center gap-3">
                    <BarChart3 aria-hidden="true" className="h-6 w-6 text-teal-400" />
                    <h3 className="text-xl font-bold text-gray-100">Backtest walk-forward point-in-time</h3>
                </div>
                <EmptyState
                    icon={BarChart3}
                    title="Ningún mes se ha simulado"
                    description="Cada corte mensual necesita al menos 253 cierres anteriores de cada símbolo del universo y el cierre de salida del mes siguiente; si el proveedor de precios no devuelve esas series, el motor descarta el corte y no queda ningún mes que medir. No se muestran ceros: un 0,00 % sin meses detrás no es un resultado."
                />
            </Card>
        );
    }

    return (
        <Card className="w-full min-w-0 overflow-hidden rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-6">
            <div className="mb-6">
                <div className="mb-2 flex items-center gap-3">
                    <BarChart3 aria-hidden="true" className="h-6 w-6 text-teal-400" />
                    <h3 className="text-xl font-bold text-gray-100">Backtest walk-forward point-in-time</h3>
                </div>
                <p className="text-sm text-gray-400">
                    {formatNumber(result.months, { maximumFractionDigits: 0 })} meses simulados,{' '}
                    {formatNumber(result.picksPorMes, { maximumFractionDigits: 0 })} picks por mes, selección
                    mensual solo con datos anteriores a cada corte.
                </p>
                <p className="mt-2 text-xs text-amber-400">
                    Mide una estrategia de momentum sobre 30 megacaps actuales. No mide la selección de calidad y valor de ProPicks.
                </p>
                {first && last && (
                    <p className="mt-2 text-xs text-gray-500">
                        Período: {/* asOf es un instante UTC (fin de mes 23:59:59Z): en la zona del mercado sigue siendo ese dia; en la del usuario saltaba al dia siguiente. */}
                        {formatMarketDate(first.asOf)} - {formatMarketDate(last.asOf)}
                    </p>
                )}
            </div>

            <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
                <Metric label="Retorno neto" value={fmtPct(result.retornoNeto)} footnote="Compuesto, descontados costes (15 pb/pata)" />
                <Metric label="Retorno bruto" value={fmtPct(result.retornoBruto)} footnote="Antes de costes" />
                <Metric label="SPY (mismo período)" value={fmtPct(result.spy)} footnote="Buy & hold" />
                <Metric
                    label="Sharpe"
                    value={formatNumber(result.sharpe, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                />
                <Metric
                    label="Sortino"
                    value={formatNumber(result.sortino, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                />
                <Metric label="Máx. drawdown" value={formatPercent(result.maxDD, { fromRatio: false, digits: 2 })} footnote="Sobre la curva neta" />
            </div>

            <div className="mb-6 min-w-0">
                <h4 className="mb-3 text-sm font-semibold text-gray-300">Desempeño mensual</h4>
                <div aria-label="Desempeño mensual del backtest" className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
                    <table className="w-full text-sm">
                        <caption className="sr-only">Desempeño mensual del backtest walk-forward: corte, picks, retorno neto, SPY y rotación</caption>
                        <thead>
                            <tr className="border-b border-gray-700">
                                <th className="py-2 text-left text-gray-400" scope="col">Corte</th>
                                <th className="py-2 text-left text-gray-400" scope="col">Picks</th>
                                <th className="py-2 text-right text-gray-400" scope="col">Mes neto</th>
                                <th className="py-2 text-right text-gray-400" scope="col">SPY</th>
                                <th className="py-2 text-right text-gray-400" scope="col">Rotación</th>
                            </tr>
                        </thead>
                        <tbody>
                            {result.tablaMensual.map((row) => (
                                <tr key={row.asOf} className="border-b border-gray-700/50">
                                    <th className="py-2 text-left text-sm font-normal text-gray-300" scope="row">{formatMarketDate(row.asOf)}</th>
                                    <td className="py-2 text-gray-400">{row.picks.join(', ')}</td>
                                    <td className={`py-2 text-right font-bold ${signedClass(row.retNeto)}`}>{fmtPct(row.retNeto)}</td>
                                    <td className={`py-2 text-right ${signedClass(row.spy)}`}>{fmtPct(row.spy)}</td>
                                    <td className="py-2 text-right text-gray-400">{formatPercent(row.turnover, { fromRatio: false, digits: 0 })}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <div className="grid grid-cols-1 gap-3 md:hidden">
                    {result.tablaMensual.map((row) => (
                        <div key={row.asOf} className="min-w-0 rounded-lg border border-gray-700/50 bg-gray-900/50 p-4">
                            <div className="flex items-center justify-between gap-2">
                                <span className="font-medium text-gray-200">{formatMarketDate(row.asOf)}</span>
                                <span className={`shrink-0 font-bold ${signedClass(row.retNeto)}`}>{fmtPct(row.retNeto)}</span>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
                                <span className="min-w-0 truncate">{row.picks.join(', ')}</span>
                                <span>SPY {fmtPct(row.spy)}</span>
                                <span>Rotación {formatPercent(row.turnover, { fromRatio: false, digits: 0 })}</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <MethodologyDisclosure title="Metodología del backtest">
                <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-gray-400">
                    <li>Walk-forward mensual: cada corte usa únicamente precios de cierre anteriores a ese corte (sin datos futuros).</li>
                    <li>Señal: momentum 12-1M (se excluye el último mes) sobre un universo líquido de 30 valores; {formatNumber(result.picksPorMes, { maximumFractionDigits: 0 })} picks equiponderados.</li>
                    <li>Costes aplicados: 15 pb por pata de rotación. Rotación media mensual: {formatPercent(result.turnover, { fromRatio: false, digits: 0 })}.</li>
                    <li>Benchmark: SPY buy & hold en el mismo período.</li>
                    <li>Sesgo de supervivencia: las 30 empresas son megacaps de hoy, elegidas con conocimiento actual; las que cayeron o salieron del índice no están.</li>
                    <li>Muestra corta: {formatNumber(result.months, { maximumFractionDigits: 0 })} meses. Sharpe, Sortino y la diferencia con SPY no son distinguibles del azar con tan pocos datos.</li>
                    <li>Precios de cierre del proveedor sin dividendos explícitos; sin impuestos ni deslizamiento más allá de los costes indicados.</li>
                    <li>La selección de ProPicks (calidad, valor, insiders, 13F) se congela cada mes en un snapshot point-in-time; ese historial es la base de un backtest futuro sin sesgo de anticipación, y todavía no hay meses suficientes.</li>
                    <li>Resultados pasados simulados no garantizan rendimientos futuros. Esto no es asesoramiento financiero.</li>
                </ul>
            </MethodologyDisclosure>
        </Card>
    );
}
