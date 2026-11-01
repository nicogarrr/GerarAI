'use client';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import { getStrategyById } from '@/lib/utils/proPicksStrategies';
import { CATEGORY_KEYS, CATEGORY_LABEL_EN, CATEGORY_LABEL_ES } from './category-display';
import type { WalkForwardBacktestResult } from '@/lib/actions/propicks-backtest.actions';

/** El backtest walk-forward llega completo desde `runWalkForwardBacktest`. */
export type FactsheetBacktest = WalkForwardBacktestResult | null | undefined;

interface StrategyFactsheetProps {
    strategyId: string;
    name: string;
    description: string;
    /** false cuando el servidor no ofrece la estrategia. */
    available: boolean;
    backtest?: FactsheetBacktest;
    loading?: boolean;
    error?: string | null;
}

/**
 * Métricas del walk-forward **global** (no de esta estrategia).
 *
 * Lo que se pinta aquí es el baseline momentum-only de la pestaña Backtesting:
 * no son las métricas de la estrategia (eso no existe y esta ficha lo dice).
 */
function globalMetrics(backtest: FactsheetBacktest) {
    const wf = (backtest ?? {}) as Partial<WalkForwardBacktestResult>;
    return {
        retorno: wf.retornoNeto ?? undefined,
        benchmark: wf.spy ?? undefined,
        // Exceso = retorno neto − SPY del mismo periodo. No es alfa de
        // regresión (no hay beta ni prima de riesgo): es la diferencia de
        // rentabilidades, y se etiqueta como tal.
        exceso:
            typeof wf.retornoNeto === 'number' && typeof wf.spy === 'number'
                ? Math.round((wf.retornoNeto - wf.spy) * 100) / 100
                : undefined,
        sharpe: wf.sharpe ?? undefined,
        maxDD: wf.maxDD ?? undefined,
        turnover: wf.turnover ?? undefined,
        period:
            wf.tablaMensual && wf.tablaMensual.length > 0
                ? {
                      start: wf.tablaMensual[0].asOf,
                      end: wf.tablaMensual[wf.tablaMensual.length - 1].asOf,
                  }
                : undefined,
    };
}

function Metric({
    label,
    value,
    footnote,
}: {
    label: string;
    value: string | undefined;
    footnote?: string;
}) {
    const t = useT();
    return (
        <div className="rounded-lg border border-gray-700/50 bg-gray-900/50 p-3">
            <div className="mb-1 text-xs text-gray-500">{label}</div>
            {value !== undefined ? (
                <div className="text-lg font-bold text-gray-100">{value}</div>
            ) : (
                <div className="text-sm font-medium text-gray-500">{t('propicks.factsheet.noData')}</div>
            )}
            {footnote && <div className="mt-1 text-[11px] text-gray-500">{footnote}</div>}
        </div>
    );
}

/**
 * Ficha de una estrategia: lo que la estrategia DECIDE (pesos por categoría y
 * score mínimo, datos reales del catálogo) y, junto a ellos, por qué aquí no
 * hay cifras de desempeño de la estrategia.
 *
 * Antes esta tarjeta solo sabía decir «Sin datos» y prometer un backtest por
 * estrategia en cuanto existieran fundamentales point-in-time. No existe tal
 * publicación: el embudo guarda un único run (el último), así que no hay la
 * serie de fundamentales con fecha de corte que necesitaría un backtest por
 * estrategia. El único backtest real del producto es el baseline global de la
 * pestaña Backtesting (momentum 12-1M sobre precios), que no depende de los
 * pesos de esta estrategia: por eso se declara aparte y nunca como su desempeño.
 */
export default function StrategyFactsheet({
    strategyId,
    name,
    description,
    available,
    backtest,
    loading,
    error,
}: StrategyFactsheetProps) {
    const strategy = getStrategyById(strategyId);
    const t = useT();
    const locale = useLocale();
    const { formatNumber, formatPercent, formatUserDate } = useFormat();
    const categoryLabels = locale === 'en' ? CATEGORY_LABEL_EN : CATEGORY_LABEL_ES;
    /** El backtest entrega porcentajes ya multiplicados por 100 (puntos, no ratio). */
    const fmtPct = (v: number | undefined, digits = 2) =>
        v === undefined
            ? undefined
            : formatPercent(v, { fromRatio: false, digits, signDisplay: 'always' });

    if (!available) {
        return (
            <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                <Badge variant="outline" className="mb-3 border-amber-500/50 text-amber-300">
                    {t('propicks.factsheet.unavailableBadge')}
                </Badge>
                <h3 className="text-lg font-semibold text-gray-100">{name}</h3>
                <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-gray-400">{description}</p>
                <p className="mx-auto mt-3 max-w-xl text-xs leading-5 text-gray-500">
                    {t('propicks.factsheet.unavailableBefore')}<span className="font-mono">{strategyId}</span>
                    {t('propicks.factsheet.unavailableAfter')}
                </p>
            </Card>
        );
    }

    if (loading && !backtest) {
        return (
            <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                <p className="text-sm text-gray-400">{t('propicks.factsheet.loading', { name })}</p>
            </Card>
        );
    }

    const hasWalkForward =
        !!backtest && 'retornoNeto' in backtest && typeof backtest.retornoNeto === 'number';

    if ((error && !backtest) || !hasWalkForward) {
        return (
            <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-semibold text-gray-100">{name}</h3>
                    <Badge variant="outline" className="border-gray-600 text-gray-300">
                        {t('propicks.factsheet.noMetricsBadge')}
                    </Badge>
                </div>
                <p className="text-sm leading-6 text-gray-400">{description}</p>
                {error && (
                    <p role="alert" className="mt-2 text-sm leading-6 text-amber-200/90">{error}</p>
                )}

                {strategy ? (
                    <div className="mt-4">
                        <h4 className="text-sm font-semibold text-gray-300">{t('propicks.factsheet.decidesTitle')}</h4>
                        <div className="mt-2 grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
                            {CATEGORY_KEYS.map((key) => (
                                <div
                                    key={key}
                                    className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-700/50 py-1.5 text-sm last:border-0 sm:[&:nth-last-child(-n+2)]:border-0"
                                >
                                    <span className="text-gray-400">{categoryLabels[key]}</span>
                                    <span className="font-medium text-gray-200">
                                        {formatPercent(strategy.categoryWeights[key], { digits: 0 })}
                                    </span>
                                </div>
                            ))}
                        </div>
                        <p className="mt-2 text-xs leading-5 text-gray-500">
                            {t('propicks.factsheet.weightsNote', { score: formatNumber(strategy.filters.minScore ?? 0, { maximumFractionDigits: 0 }) })}
                            <span className="font-mono">{t('propicks.factsheet.naMarker')}</span>.
                        </p>
                    </div>
                ) : null}

                <div className="mt-4 rounded-lg border border-gray-700/50 bg-gray-900/50 p-3">
                    <h4 className="text-sm font-semibold text-gray-300">{t('propicks.factsheet.whyNoFiguresTitle')}</h4>
                    <p className="mt-1 text-xs leading-5 text-gray-500">
                        {t('propicks.factsheet.whyNoFiguresBefore')}<em>{t('propicks.factsheet.whyNoFiguresEmphasis')}</em>{' '}
                        {t('propicks.factsheet.whyNoFiguresAfter')}
                    </p>
                    <p className="mt-2 text-xs leading-5 text-gray-500">
                        {t('propicks.factsheet.onlyBacktestBefore')}{' '}
                        <span className="font-medium text-gray-300">{t('propicks.factsheet.backtestTab')}</span>{' '}
                        {t('propicks.factsheet.onlyBacktestAfter')}
                    </p>
                </div>
            </Card>
        );
    }

    const m = globalMetrics(backtest);
    const period = m.period;

    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-6">
            <div className="mb-1 flex flex-wrap items-center gap-2">
                <h3 className="text-lg font-semibold text-gray-100">{name}</h3>
                <Badge variant="outline" className="border-teal-500/50 text-teal-300">
                    {t('propicks.factsheet.globalBadge')}
                </Badge>
            </div>
            <p className="text-sm leading-6 text-gray-400">{description}</p>
            <p className="mt-1 text-xs text-gray-500">
                {t('propicks.factsheet.period', {
                    from: period?.start ? formatUserDate(period.start) : t('propicks.factsheet.noData'),
                    to: period?.end ? formatUserDate(period.end) : t('propicks.factsheet.noData'),
                })}
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
                <Metric label={t('propicks.factsheet.netReturn')} value={fmtPct(m.retorno)} footnote={t('propicks.factsheet.netReturnNote')} />
                <Metric label={t('propicks.factsheet.spyBenchmark')} value={fmtPct(m.benchmark)} footnote={t('propicks.factsheet.samePeriod')} />
                <Metric
                    label={t('propicks.factsheet.netSharpe')}
                    value={
                        m.sharpe === undefined
                            ? undefined
                            : formatNumber(m.sharpe, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                    }
                />
                <Metric
                    label={t('propicks.factsheet.maxDrawdown')}
                    value={m.maxDD === undefined ? undefined : formatPercent(m.maxDD, { fromRatio: false, digits: 2 })}
                />
                <Metric
                    label={t('propicks.factsheet.avgTurnover')}
                    value={m.turnover === undefined ? undefined : formatPercent(m.turnover, { fromRatio: false, digits: 0 })}
                    footnote="Turnover"
                />
                <Metric label={t('propicks.factsheet.excessVsSpy')} value={fmtPct(m.exceso)} footnote={t('propicks.factsheet.excessNote')} />
            </div>
            <p className="mt-4 text-xs leading-5 text-gray-500">
                {t('propicks.factsheet.footer')}
            </p>
        </Card>
    );
}