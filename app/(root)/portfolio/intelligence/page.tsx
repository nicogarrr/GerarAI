import type { Metadata } from 'next';
import { xirrUnavailableReason } from '@/lib/research/xirr-status';
import { etiquetaComponenteAtribucion } from '@/lib/labels';
import Link from 'next/link';
import { ArrowLeft, AlertTriangle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Panel } from '@/components/ui/panel';
import BackendOffline from '@/components/system/BackendOffline';
import { getPortfolioIntelligence, type PortfolioIntelligence } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT, getFormat } from '@/lib/i18n/server';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';



const LEDGER_LABEL_KEYS = {
  missing_ledger: 'portfolio.intelligence.ledger_missing_ledger',
  incomplete_ledger: 'portfolio.intelligence.ledger_incomplete_ledger',
  missing_fx: 'portfolio.intelligence.ledger_missing_fx',
  missing_start_price: 'portfolio.intelligence.ledger_missing_start_price',
  missing_start_fx: 'portfolio.intelligence.ledger_missing_start_fx',
  missing_end_value: 'portfolio.intelligence.ledger_missing_end_value',
} as const;
const LEDGER_REASON_KEYS = Object.keys(LEDGER_LABEL_KEYS) as Array<keyof typeof LEDGER_LABEL_KEYS>;

const ATTRIBUTION_ND_LABEL_KEYS = {
  fundamental_growth: 'portfolio.intelligence.attrNd_fundamental_growth',
  multiple: 'portfolio.intelligence.attrNd_multiple',
  dividends: 'portfolio.intelligence.attrNd_dividends',
  buybacks: 'portfolio.intelligence.attrNd_buybacks',
  dilution: 'portfolio.intelligence.attrNd_dilution',
  fx: 'portfolio.intelligence.attrNd_fx',
  sizing: 'portfolio.intelligence.attrNd_sizing',
} as const;
const ATTRIBUTION_ND_KEYS = Object.keys(ATTRIBUTION_ND_LABEL_KEYS) as Array<keyof typeof ATTRIBUTION_ND_LABEL_KEYS>;

type LedgerReason = keyof typeof LEDGER_LABEL_KEYS;
type AttributionNdReason = keyof typeof ATTRIBUTION_ND_LABEL_KEYS;

function ledgerReasonLabel(ti: TFunction, key: string): string {
  const reason: LedgerReason = (LEDGER_REASON_KEYS as readonly string[]).includes(key) ? (key as LedgerReason) : 'missing_ledger';
  return (LEDGER_REASON_KEYS as readonly string[]).includes(key)
    ? ti(LEDGER_LABEL_KEYS[reason])
    : ti('portfolio.intelligence.ledger_fallback');
}

function attributionNdLabel(ti: TFunction, key: string): string {
  return (ATTRIBUTION_ND_KEYS as readonly string[]).includes(key)
    ? ti(ATTRIBUTION_ND_LABEL_KEYS[key as AttributionNdReason])
    : ti('portfolio.intelligence.attrNd_fallback');
}

/** Celda de atribución: N/D con el motivo a mano (title) en vez de un 0,0 % inventado. */
function attributionCell(ti: TFunction, f: Formatters, value: number | null, key: string) {
  if (value === null) {
    const na = ti('common.na');
    return <span title={ti('portfolio.intelligence.attrNdTitle', { na, reason: attributionNdLabel(ti, key) })}>{na}</span>;
  }
  return f.formatPercent(value, { digits: 1 });
}

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const ti = await getT();
  return {
    title: ti('portfolio.intelligence.metaTitle'),
    description: ti('portfolio.intelligence.metaDescription'),
  };
}


export default async function PortfolioIntelligencePage({ searchParams }: { searchParams: Promise<{ years?: string }> }) {
  const ti = await getT();
  const f = await getFormat();
  const na = ti('common.na');
  /** Porcentaje ligado al locale. `null` es "sin dato" (NA), `0` es un 0,00 % legítimo. */
  const pct = (value: number | null) => f.formatPercent(value, { digits: 1 });
  /** Ratio ligado al locale (Sharpe, Beta, Calmar…). `null` es "sin dato" (NA). */
  const ratio = (value: number | null) => f.formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const query = await searchParams;
  const years = Math.max(1, Math.min(20, Number(query.years) || 5));
  // Sin este catch, un backend apagado (o un 5xx al calcular la analítica)
  // subía al ErrorBoundary global y el usuario se quedaba con una pantalla de
  // "se produjo un error inesperado" sin saber que era algo temporal.
  let data: PortfolioIntelligence;
  try {
    data = await getPortfolioIntelligence(years);
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature={ti('portfolio.intelligence.featureName')} retryHref={`/portfolio/intelligence?years=${years}`} />;
    }
    throw error;
  }
  const tickers = Object.keys(data.risk.correlations);
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6"><header className="flex flex-col gap-4 border-b border-gray-800 pb-5 md:flex-row md:items-end"><div><Button asChild className="mb-4" size="sm" variant="ghost"><Link href="/portfolio"><ArrowLeft aria-hidden="true" className="h-4 w-4" />{ti('portfolio.intelligence.backToPortfolio')}</Link></Button><p className="text-sm font-semibold uppercase text-teal-300">{ti('portfolio.intelligence.kicker')}</p><h1 className="mt-1 text-3xl font-bold text-gray-100">{ti('portfolio.intelligence.title')}</h1><p className="mt-2 text-sm text-gray-400">{ti('portfolio.intelligence.subtitlePrefix')}<Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300 hover:text-teal-200" href="/risk">{ti('portfolio.intelligence.subtitleLink')}</Link>.</p></div><form className="flex flex-wrap items-end gap-2 md:ml-auto" method="get"><div><label className="mb-1 block text-xs text-gray-400" htmlFor="intelligence-years">{ti('portfolio.intelligence.yearsLabel')}</label><Input id="intelligence-years" className="min-h-11 w-24" max="20" min="1" name="years" defaultValue={years} type="number" /></div><Button type="submit">{ti('portfolio.intelligence.apply')}</Button></form></header>
    <Link className="inline-flex min-h-11 items-center text-sm text-teal-300 hover:text-teal-200" href="/portfolio/stress">{ti('portfolio.intelligence.stressLink')}</Link>
    <section className={`rounded-xl border p-4 ${data.performance.twr_is_exact ? 'border-teal-900/60 bg-teal-950/20' : 'border-amber-900/60 bg-amber-950/20'}`}><div className="flex items-start gap-3"><AlertTriangle aria-hidden="true" className={`mt-0.5 h-5 w-5 shrink-0 ${data.performance.twr_is_exact ? 'text-teal-300' : 'text-amber-300'}`} /><div><h2 className={`font-semibold ${data.performance.twr_is_exact ? 'text-teal-200' : 'text-amber-200'}`}>{data.performance.twr_is_exact ? ti('portfolio.intelligence.twrExactTitle') : ti('portfolio.intelligence.twrIndicativeTitle')}</h2><p className="mt-1 text-sm leading-6 text-gray-400">{data.performance.twr_is_exact ? ti('portfolio.intelligence.twrExactBody', { n: data.coverage.snapshot_returns }) : ti('portfolio.intelligence.twrIndicativeBody')}{ti('portfolio.intelligence.attributionNote')}{data.performance.twr_is_exact ? '' : ti('portfolio.intelligence.notComparable', { years: data.horizon_years })}{data.performance.xirr === null ? ti('portfolio.intelligence.xirrSuffix', { na, reason: xirrUnavailableReason(data.performance.trace?.status) }) : ''}</p></div></div></section>
    <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[[data.performance.twr_is_exact ? ti('portfolio.intelligence.kpiTwrDaily') : ti('portfolio.intelligence.kpiTwrIndicative'), pct(data.performance.twr)], [ti('portfolio.intelligence.kpiXirr'), pct(data.performance.xirr)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.kpiMaxDrawdown') : ti('portfolio.intelligence.kpiMaxDrawdownIndicative'), pct(data.risk.max_drawdown)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.kpiSharpe') : ti('portfolio.intelligence.kpiSharpeIndicative'), ratio(data.risk.sharpe)]].map(([label, value]) => <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={label}><div className="text-xs font-semibold uppercase text-gray-500">{label}</div><div className="mt-2 text-2xl font-semibold text-gray-100">{value}</div></div>)}</section>
    {/*
        Once métricas en la primera rejilla eran once cosas que leer antes de
        llegar a nada. Quedan las cuatro que resumen el resultado (retorno,
        dinero, caída y calidad del retorno) y las otras siete se plegan: están
        calculadas y siguen a un clic, no desaparecen.
    */}
    <Panel collapsible defaultOpen={false} description={ti('portfolio.intelligence.advancedDescription')} title={ti('portfolio.intelligence.advancedTitle')}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[[data.performance.twr_is_exact ? ti('portfolio.intelligence.metricAnnualized') : ti('portfolio.intelligence.metricAnnualizedIndicative'), pct(data.performance.annualized_return)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.metricVolatility') : ti('portfolio.intelligence.metricVolatilityIndicative'), pct(data.risk.volatility)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.metricSortino') : ti('portfolio.intelligence.metricSortinoIndicative'), ratio(data.risk.sortino)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.metricVar') : ti('portfolio.intelligence.metricVarIndicative'), pct(data.risk.var_95)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.metricCvar') : ti('portfolio.intelligence.metricCvarIndicative'), pct(data.risk.cvar_95)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.metricCalmar') : ti('portfolio.intelligence.metricCalmarIndicative'), ratio(data.risk.calmar)], [data.performance.twr_is_exact ? ti('portfolio.intelligence.metricBeta') : ti('portfolio.intelligence.metricBetaIndicative'), ratio(data.risk.beta)]].map(([label, value]) => <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={label}><div className="text-xs font-semibold uppercase text-gray-500">{label}</div><div className="mt-2 text-xl font-semibold text-gray-100">{value}</div></div>)}</div>
    </Panel>
    {/*
        Las exposiciones por sector, país, divisa y factor se pintaban aquí y en
        /risk, que es donde el motor las calcula y donde se disparan las alertas
        de concentración. Aquí solo queda el resumen numérico que hace falta
        para leer el riesgo, con la salida al sitio único.
    */}
    <Panel
      actions={<Link className="inline-flex min-h-11 items-center text-sm text-teal-300 hover:text-teal-200" href="/risk">{ti('portfolio.intelligence.concentrationAction')}</Link>}
      description={ti('portfolio.intelligence.concentrationDescription')}
      title={ti('portfolio.intelligence.concentrationTitle')}
    >
      <div className="grid gap-3 text-sm sm:grid-cols-3">
        <div className="flex justify-between gap-3"><span className="text-gray-400">{ti('portfolio.intelligence.top1')}</span><span className="text-gray-200">{pct(data.concentration.top_1)}</span></div>
        <div className="flex justify-between gap-3"><span className="text-gray-400">{ti('portfolio.intelligence.top5')}</span><span className="text-gray-200">{pct(data.concentration.top_5)}</span></div>
        <div className="flex justify-between gap-3"><span className="text-gray-400">{ti('portfolio.intelligence.herfindahl')}</span><span className="text-gray-200">{f.formatNumber(data.concentration.herfindahl, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</span></div>
      </div>
      <p className="mt-4 border-t border-gray-800 pt-3 text-gray-500">{data.coverage.positions === 0 ? ti('portfolio.intelligence.coverageNone') : ti('portfolio.intelligence.coverageLine', { withHistory: data.coverage.positions_with_price_history, positions: data.coverage.positions, fullHorizon: data.coverage.positions_with_full_horizon, positions2: data.coverage.positions, years: data.horizon_years, percent: f.formatPercent(data.coverage.price_history_window_percent, { fromRatio: false, digits: 0 }) })}</p>
    </Panel>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="flex flex-col gap-2 md:flex-row md:items-center"><h2 className="font-semibold text-gray-100">{ti('portfolio.intelligence.benchmarkTitle', { symbol: data.benchmark.symbol })}</h2>{data.benchmark.status !== 'calculated' ? <Badge className="md:ml-auto" variant="outline">{data.benchmark.status === 'missing_benchmark' ? ti('portfolio.intelligence.benchmarkMissing') : ti('portfolio.intelligence.benchmarkOverlap', { n: data.benchmark.observations })}</Badge> : null}</div>{data.benchmark.status === 'calculated' ? <section className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[[ti('portfolio.intelligence.benchmarkPortfolioAnnualized'), pct(data.benchmark.portfolio_annualized)], [ti('portfolio.intelligence.benchmarkSymbolAnnualized', { symbol: data.benchmark.symbol }), pct(data.benchmark.benchmark_annualized)], [ti('portfolio.intelligence.benchmarkAlpha'), pct(data.benchmark.alpha_annualized)], [ti('portfolio.intelligence.benchmarkTrackingError'), pct(data.benchmark.tracking_error)], [ti('portfolio.intelligence.benchmarkInformationRatio'), ratio(data.benchmark.information_ratio)], [ti('portfolio.intelligence.benchmarkObservations'), String(data.benchmark.observations)]].map(([label, value]) => <div className="rounded-xl border border-gray-800 bg-gray-900/40 p-4" key={label}><div className="text-xs font-semibold uppercase text-gray-500">{label}</div><div className="mt-2 text-xl font-semibold text-gray-100">{value}</div></div>)}</section> : <p className="mt-3 text-sm text-gray-400">{ti('portfolio.intelligence.benchmarkRequirement')}</p>}</section>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="flex flex-col gap-2 md:flex-row md:items-center"><h2 className="font-semibold text-gray-100">{ti('portfolio.intelligence.contributionTitle')}</h2><Badge className="md:ml-auto" variant="outline">{data.ledger_contribution.coverage.positions === 0 ? ti('portfolio.intelligence.contributionBadgeNone') : ti('portfolio.intelligence.contributionBadgeSome', { withContribution: data.ledger_contribution.coverage.with_contribution, positions: data.ledger_contribution.coverage.positions })}</Badge></div><p className="mt-2 text-xs text-gray-500">{ti('portfolio.intelligence.contributionNoteStart')}{data.ledger_contribution.base_currency ? ti('portfolio.intelligence.contributionNoteCurrency', { currency: data.ledger_contribution.base_currency }) : ''}{ti('portfolio.intelligence.contributionNoteEnd')}</p><div aria-label={ti('portfolio.intelligence.contributionAria')} className="scroll-affordance-x mt-4 overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}><table className="w-full min-w-[760px] text-left text-sm"><caption className="sr-only">{ti('portfolio.intelligence.contributionCaption')}</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">{ti('portfolio.intelligence.colTicker')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colStartValue')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colEndValue')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colNetInvested')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colIncome')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colPnl')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colWeight')}</th></tr></thead><tbody>{data.ledger_contribution.positions.map((row) => <tr className="border-b border-gray-900" key={row.ticker}><th className="py-3 text-left text-sm font-semibold text-teal-300" scope="row">{row.ticker}</th><td className="py-3 text-right">{f.formatNumber(row.start_value, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{f.formatNumber(row.end_value, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{f.formatNumber(row.net_invested, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{f.formatNumber(row.income, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{row.contribution_pnl === null ? ti('portfolio.intelligence.pnlNdSuffix', { na, reason: ledgerReasonLabel(ti, row.reason ?? '') }) : f.formatNumber(row.contribution_pnl, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{pct(row.contribution_share)}</td></tr>)}</tbody></table></div>{data.ledger_contribution.total_pnl !== null ? <p className="mt-3 text-sm text-gray-400">{data.ledger_contribution.coverage.with_contribution < data.ledger_contribution.coverage.positions ? ti('portfolio.intelligence.totalPnlPartial', { withContribution: data.ledger_contribution.coverage.with_contribution, positions: data.ledger_contribution.coverage.positions }) : ti('portfolio.intelligence.totalPnlFull')}: <span className="font-semibold text-gray-100">{f.formatNumber(data.ledger_contribution.total_pnl, { maximumFractionDigits: 0 })} {data.ledger_contribution.base_currency}</span></p> : <p className="mt-3 text-sm text-gray-400">{ti('portfolio.intelligence.totalPnlNoData')}</p>}</section>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="flex flex-col gap-2 md:flex-row md:items-center"><h2 className="font-semibold text-gray-100">{ti('portfolio.intelligence.attributionTitle')}</h2><Badge className="md:ml-auto" variant="outline">{ti('portfolio.intelligence.attributionBadge')}</Badge></div><p className="mt-2 text-xs text-gray-500">{ti('portfolio.intelligence.attributionNoteStart')}{data.attribution.period_start && data.attribution.period_end ? ti('portfolio.intelligence.attributionNotePeriod', { start: f.formatMarketDate(data.attribution.period_start), end: f.formatMarketDate(data.attribution.period_end) }) : ti('portfolio.intelligence.attributionNoteHorizon', { years: data.horizon_years })}{ti('portfolio.intelligence.attributionNoteEnd')}</p><div aria-label={ti('portfolio.intelligence.attributionAria')} className="scroll-affordance-x mt-4 overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}><table className="w-full min-w-[1050px] text-left text-sm"><caption className="sr-only">{ti('portfolio.intelligence.attributionCaption')}</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">{ti('portfolio.intelligence.colTicker')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colWeightOnEquity')}</th><th className="border-b border-gray-800 py-2 text-right" scope="col">{ti('portfolio.intelligence.colPriceReturn')}</th>{Object.keys(data.attribution.portfolio_components).map((key) => <th className="border-b border-gray-800 py-2 text-right" key={key} scope="col">{etiquetaComponenteAtribucion(key)}</th>)}</tr></thead><tbody>{data.attribution.positions.map((row) => <tr className="border-b border-gray-900" key={row.ticker}><th className="py-3 text-left text-sm font-semibold text-teal-300" scope="row">{row.ticker}{row.partial_history && row.period_start ? <Badge className="ml-2" variant="outline" title={ti('portfolio.intelligence.partialHistoryTitle')}>{ti('portfolio.intelligence.partialHistoryText', { date: f.formatMarketDate(row.period_start) })}</Badge> : null}</th><td className="py-3 text-right">{pct(row.weight)}</td><td className="py-3 text-right" title={row.period_start && row.period_end ? `${f.formatMarketDate(row.period_start)} - ${f.formatMarketDate(row.period_end)}` : undefined}>{pct(row.total_return)}</td>{Object.keys(data.attribution.portfolio_components).map((key) => <td className="py-3 text-right text-gray-400" key={key}>{attributionCell(ti, f, row.components[key] ?? null, key)}</td>)}</tr>)}</tbody></table></div>{data.attribution.excluded_partial_histories && data.attribution.excluded_partial_histories.length > 0 ? <p className="mt-3 text-xs text-amber-300/90">{ti('portfolio.intelligence.excludedNote', { tickers: data.attribution.excluded_partial_histories.join(', ') })}</p> : null}</section>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><h2 className="font-semibold text-gray-100">{ti('portfolio.intelligence.correlationsTitle')}</h2><p className="mt-2 text-xs text-gray-500">{ti('portfolio.intelligence.correlationsNote', { min: data.risk.correlation_min_observations, na })}</p><div aria-label={ti('portfolio.intelligence.correlationsAria')} className="scroll-affordance-x mt-4 overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}><table className="text-sm"><caption className="sr-only">{ti('portfolio.intelligence.correlationsCaption')}</caption><thead><tr><th className="p-2" scope="col"><span className="sr-only">{ti('portfolio.intelligence.correlationsVariable')}</span></th>{tickers.map((ticker) => <th className="p-2 text-gray-400" key={ticker} scope="col">{ticker}</th>)}</tr></thead><tbody>{tickers.map((left) => <tr key={left}><th className="p-2 text-left text-sm font-normal text-gray-400" scope="row">{left}</th>{tickers.map((right) => { const correlation = data.risk.correlations[left]?.[right]; const observations = data.risk.correlation_observations?.[left]?.[right] ?? 0; const insufficient = left !== right && observations < data.risk.correlation_min_observations; const title = left === right ? undefined : insufficient ? ti('portfolio.intelligence.corrTitleInsufficient', { n: observations, min: data.risk.correlation_min_observations }) : ti('portfolio.intelligence.corrTitleOk', { n: observations }); return <td className="min-w-16 border border-gray-900 p-2 text-center text-gray-300" key={right} title={title} style={{ backgroundColor: correlation === null || correlation === undefined ? 'transparent' : correlation >= 0 ? `rgb(13 148 136 / ${Math.abs(correlation) * 0.35})` : `rgb(239 68 68 / ${Math.abs(correlation) * 0.35})` }}>{correlation === null || correlation === undefined ? na : f.formatNumber(correlation, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>; })}</tr>)}</tbody></table></div></section>
  </main>;
}
