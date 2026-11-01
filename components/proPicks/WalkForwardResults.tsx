'use client';

import { Card } from '@/components/ui/card';
import { MethodologyDisclosure } from '@/components/ui/methodology-disclosure';
import { EmptyState } from '@/components/ui/empty-state';
import { BarChart3 } from 'lucide-react';
import { useFormat, useT } from '@/lib/i18n/client';
import type { WalkForwardBacktestResult } from '@/lib/actions/propicks-backtest.actions';

interface WalkForwardResultsProps {
    result: WalkForwardBacktestResult;
}

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
    const t = useT();
    const { formatMarketDate, formatNumber, formatPercent } = useFormat();
    /** El backtest entrega porcentajes ya multiplicados por 100 (puntos, no ratio). */
    const fmtPct = (v: number, digits = 2) =>
        formatPercent(v, { fromRatio: false, digits, signDisplay: 'always' });
    const months = formatNumber(result.months, { maximumFractionDigits: 0 });
    const picksPerMonth = formatNumber(result.picksPorMes, { maximumFractionDigits: 0 });
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
                    <h3 className="text-xl font-bold text-gray-100">{t('propicks.walkForward.title')}</h3>
                </div>
                <EmptyState
                    icon={BarChart3}
                    title={t('propicks.walkForward.emptyTitle')}
                    description={t('propicks.walkForward.emptyDescription')}
                />
            </Card>
        );
    }

    return (
        <Card className="w-full min-w-0 overflow-hidden rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-6">
            <div className="mb-6">
                <div className="mb-2 flex items-center gap-3">
                    <BarChart3 aria-hidden="true" className="h-6 w-6 text-teal-400" />
                    <h3 className="text-xl font-bold text-gray-100">{t('propicks.walkForward.title')}</h3>
                </div>
                <p className="text-sm text-gray-400">
                    {t('propicks.walkForward.summary', { months, picks: picksPerMonth })}
                </p>
                <p className="mt-2 text-xs text-amber-400">
                    {t('propicks.walkForward.scopeWarning')}
                </p>
                {first && last && (
                    <p className="mt-2 text-xs text-gray-500">
                        {/* asOf es un instante UTC (fin de mes 23:59:59Z): en la zona del mercado sigue siendo ese dia; en la del usuario saltaba al dia siguiente. */}
                        {t('propicks.walkForward.period', { from: formatMarketDate(first.asOf), to: formatMarketDate(last.asOf) })}
                    </p>
                )}
            </div>

            <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
                <Metric label={t('propicks.walkForward.netReturn')} value={fmtPct(result.retornoNeto)} footnote={t('propicks.walkForward.netReturnNote')} />
                <Metric label={t('propicks.walkForward.grossReturn')} value={fmtPct(result.retornoBruto)} footnote={t('propicks.walkForward.grossReturnNote')} />
                <Metric label={t('propicks.walkForward.spySamePeriod')} value={fmtPct(result.spy)} footnote="Buy & hold" />
                <Metric
                    label="Sharpe"
                    value={formatNumber(result.sharpe, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                />
                <Metric
                    label="Sortino"
                    value={formatNumber(result.sortino, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                />
                <Metric label={t('propicks.walkForward.maxDrawdown')} value={formatPercent(result.maxDD, { fromRatio: false, digits: 2 })} footnote={t('propicks.walkForward.maxDrawdownNote')} />
            </div>

            <div className="mb-6 min-w-0">
                <h4 className="mb-3 text-sm font-semibold text-gray-300">{t('propicks.walkForward.monthlyTitle')}</h4>
                <div aria-label={t('propicks.walkForward.monthlyAria')} className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
                    <table className="w-full text-sm">
                        <caption className="sr-only">{t('propicks.walkForward.monthlyCaption')}</caption>
                        <thead>
                            <tr className="border-b border-gray-700">
                                <th className="py-2 text-left text-gray-400" scope="col">{t('propicks.walkForward.colCutoff')}</th>
                                <th className="py-2 text-left text-gray-400" scope="col">Picks</th>
                                <th className="py-2 text-right text-gray-400" scope="col">{t('propicks.walkForward.colNetMonth')}</th>
                                <th className="py-2 text-right text-gray-400" scope="col">SPY</th>
                                <th className="py-2 text-right text-gray-400" scope="col">{t('propicks.walkForward.colTurnover')}</th>
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
                                <span>{t('propicks.walkForward.turnoverValue', { value: formatPercent(row.turnover, { fromRatio: false, digits: 0 }) })}</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <MethodologyDisclosure title={t('propicks.walkForward.methodologyTitle')}>
                <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-gray-400">
                    <li>{t('propicks.walkForward.method.pointInTime')}</li>
                    <li>{t('propicks.walkForward.method.signal', { picks: picksPerMonth })}</li>
                    <li>{t('propicks.walkForward.method.costs', { turnover: formatPercent(result.turnover, { fromRatio: false, digits: 0 }) })}</li>
                    <li>{t('propicks.walkForward.method.benchmark')}</li>
                    <li>{t('propicks.walkForward.method.survivorship')}</li>
                    <li>{t('propicks.walkForward.method.shortSample', { months })}</li>
                    <li>{t('propicks.walkForward.method.prices')}</li>
                    <li>{t('propicks.walkForward.method.snapshots')}</li>
                    <li>{t('propicks.walkForward.method.disclaimer')}</li>
                </ul>
            </MethodologyDisclosure>
        </Card>
    );
}
