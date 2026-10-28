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
import { formatMarketDate, formatNumber, formatPercent, NA } from '@/lib/format';



const LEDGER_REASON_LABELS: Record<string, string> = {
  missing_ledger: 'sin registro de transacciones',
  incomplete_ledger: 'registro de transacciones incompleto',
  missing_fx: 'sin tipo de cambio',
  missing_start_price: 'sin precio al inicio del horizonte',
  missing_start_fx: 'sin tipo de cambio al inicio del horizonte',
  missing_end_value: 'sin valor actual en divisa base',
};


const ATTRIBUTION_ND_REASONS: Record<string, string> = {
  fundamental_growth: 'sin BPA anual en el horizonte',
  multiple: 'depende de componentes sin dato',
  dividends: 'sin dividendos en el registro de transacciones',
  buybacks: 'sin cifras de acciones en el horizonte',
  dilution: 'sin cifras de acciones en el horizonte',
  fx: 'sin tipo de cambio',
  sizing: 'sin precios en el horizonte',
};

/** Celda de atribución: N/D con el motivo a mano (title) en vez de un 0,0 % inventado. */
function attributionCell(value: number | null, key: string) {
  if (value === null) return <span title={`N/D: ${ATTRIBUTION_ND_REASONS[key] ?? 'sin dato'}`}>{NA}</span>;
  return pct(value);
}

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
  title: 'Inteligencia de cartera',
  description:
    'Rendimiento y riesgo histórico de la cartera: TWR, XIRR, caída máxima, volatilidad, VaR, correlaciones y atribución, con cobertura de datos y limitaciones explícitas. Las concentraciones están en Exposiciones de cartera.',
};

/** Porcentaje en es-ES. `null` es "sin dato" (NA), `0` es un 0,00 % legítimo. */
function pct(value: number | null) { return formatPercent(value, { digits: 1 }); }
/** Ratio en es-ES (Sharpe, Beta, Calmar…). `null` es "sin dato" (NA). */
function ratio(value: number | null) { return formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }


export default async function PortfolioIntelligencePage({ searchParams }: { searchParams: Promise<{ years?: string }> }) {
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
      return <BackendOffline feature="Inteligencia de cartera" retryHref={`/portfolio/intelligence?years=${years}`} />;
    }
    throw error;
  }
  const tickers = Object.keys(data.risk.correlations);
  return <main id="content" tabIndex={-1} className="mx-auto flex max-w-7xl flex-col gap-6"><header className="flex flex-col gap-4 border-b border-gray-800 pb-5 md:flex-row md:items-end"><div><Button asChild className="mb-4" size="sm" variant="ghost"><Link href="/portfolio"><ArrowLeft aria-hidden="true" className="h-4 w-4" />Cartera</Link></Button><p className="text-sm font-semibold uppercase text-teal-300">Rendimiento y riesgo</p><h1 className="mt-1 text-3xl font-bold text-gray-100">Inteligencia de cartera</h1><p className="mt-2 text-sm text-gray-400">Rendimiento y riesgo histórico de la cartera, con cobertura de datos y limitaciones metodológicas explícitas. Las concentraciones están en <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300 hover:text-teal-200" href="/risk">Exposiciones</Link>.</p></div><form className="flex flex-wrap items-end gap-2 md:ml-auto" method="get"><div><label className="mb-1 block text-xs text-gray-400" htmlFor="intelligence-years">Periodo de análisis (años)</label><Input id="intelligence-years" className="min-h-11 w-24" max="20" min="1" name="years" defaultValue={years} type="number" /></div><Button type="submit">Aplicar</Button></form></header>
    <Link className="inline-flex min-h-11 items-center text-sm text-teal-300 hover:text-teal-200" href="/portfolio/stress">Estrés histórico · 2008 / 2020 / 2022</Link>
    <section className={`rounded-xl border p-4 ${data.performance.twr_is_exact ? 'border-teal-900/60 bg-teal-950/20' : 'border-amber-900/60 bg-amber-950/20'}`}><div className="flex items-start gap-3"><AlertTriangle aria-hidden="true" className={`mt-0.5 h-5 w-5 shrink-0 ${data.performance.twr_is_exact ? 'text-teal-300' : 'text-amber-300'}`} /><div><h2 className={`font-semibold ${data.performance.twr_is_exact ? 'text-teal-200' : 'text-amber-200'}`}>{data.performance.twr_is_exact ? 'TWR diario con historial de cartera' : 'Indicativo: no es rendimiento contable exacto'}</h2><p className="mt-1 text-sm leading-6 text-gray-400">{data.performance.twr_is_exact ? `El TWR enlaza ${data.coverage.snapshot_returns} retornos diarios completos con posiciones, caja, FX y flujos externos persistidos.` : 'El TWR usa pesos estáticos actuales hasta que existan registros diarios completos de posiciones y caja.'} La atribución sigue siendo heurística, no por lotes de transacciones ni tipo Brinson.{data.performance.twr_is_exact ? '' : ` Estas cifras no son comparables con la ganancia o pérdida desde compra de Cartera: miden el precio de las posiciones actuales en un horizonte de hasta ${data.horizon_years} años, no tus aportaciones ni tu coste.`}{data.performance.xirr === null ? ` XIRR: ${NA}, ${xirrUnavailableReason(data.performance.trace?.status)}.` : ''}</p></div></div></section>
    <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[[data.performance.twr_is_exact ? 'TWR diario' : 'TWR indicativo', pct(data.performance.twr)], ['XIRR', pct(data.performance.xirr)], [data.performance.twr_is_exact ? 'Máx. caída' : 'Máx. caída indicativa', pct(data.risk.max_drawdown)], [data.performance.twr_is_exact ? 'Sharpe' : 'Sharpe indicativo', ratio(data.risk.sharpe)]].map(([label, value]) => <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={label}><div className="text-xs font-semibold uppercase text-gray-500">{label}</div><div className="mt-2 text-2xl font-semibold text-gray-100">{value}</div></div>)}</section>
    {/*
        Once métricas en la primera rejilla eran once cosas que leer antes de
        llegar a nada. Quedan las cuatro que resumen el resultado (retorno,
        dinero, caída y calidad del retorno) y las otras siete se plegan: están
        calculadas y siguen a un clic, no desaparecen.
    */}
    <Panel collapsible defaultOpen={false} description="Anualizado, volatilidad, Sortino, VaR, CVaR, Calmar y Beta. Mismo cálculo que las cuatro de arriba, con más decimales para el diagnóstico." title="Detalle avanzado">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[[data.performance.twr_is_exact ? 'Anualizado' : 'Anualizado indicativo', pct(data.performance.annualized_return)], [data.performance.twr_is_exact ? 'Volatilidad' : 'Volatilidad indicativa', pct(data.risk.volatility)], [data.performance.twr_is_exact ? 'Sortino' : 'Sortino indicativo', ratio(data.risk.sortino)], [data.performance.twr_is_exact ? 'VaR 95%' : 'VaR 95% indicativo', pct(data.risk.var_95)], [data.performance.twr_is_exact ? 'CVaR 95%' : 'CVaR 95% indicativo', pct(data.risk.cvar_95)], [data.performance.twr_is_exact ? 'Calmar' : 'Calmar indicativo', ratio(data.risk.calmar)], [data.performance.twr_is_exact ? 'Beta' : 'Beta indicativa', ratio(data.risk.beta)]].map(([label, value]) => <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={label}><div className="text-xs font-semibold uppercase text-gray-500">{label}</div><div className="mt-2 text-xl font-semibold text-gray-100">{value}</div></div>)}</div>
    </Panel>
    {/*
        Las exposiciones por sector, país, divisa y factor se pintaban aquí y en
        /risk, que es donde el motor las calcula y donde se disparan las alertas
        de concentración. Aquí solo queda el resumen numérico que hace falta
        para leer el riesgo, con la salida al sitio único.
    */}
    <Panel
      actions={<Link className="inline-flex min-h-11 items-center text-sm text-teal-300 hover:text-teal-200" href="/risk">Ver concentraciones</Link>}
      description="Pesos sobre el valor de las posiciones de renta variable, sin caja; Exposiciones de cartera calcula sobre el total con caja. El desglose completo está en Exposiciones de cartera."
      title="Concentración de la cartera"
    >
      <div className="grid gap-3 text-sm sm:grid-cols-3">
        <div className="flex justify-between gap-3"><span className="text-gray-400">Top 1 sobre renta variable</span><span className="text-gray-200">{pct(data.concentration.top_1)}</span></div>
        <div className="flex justify-between gap-3"><span className="text-gray-400">Top 5 sobre renta variable</span><span className="text-gray-200">{pct(data.concentration.top_5)}</span></div>
        <div className="flex justify-between gap-3"><span className="text-gray-400">Herfindahl (sobre renta variable)</span><span className="text-gray-200">{formatNumber(data.concentration.herfindahl, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</span></div>
      </div>
      <p className="mt-4 border-t border-gray-800 pt-3 text-gray-500">{data.coverage.positions === 0 ? 'Sin posiciones que valorar todavía.' : `${data.coverage.positions_with_price_history}/${data.coverage.positions} posiciones con histórico de precios; ${data.coverage.positions_with_full_horizon}/${data.coverage.positions} cubren todo el horizonte de ${data.horizon_years} años (cobertura media del horizonte: ${formatPercent(data.coverage.price_history_window_percent, { fromRatio: false, digits: 0 })})`}</p>
    </Panel>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="flex flex-col gap-2 md:flex-row md:items-center"><h2 className="font-semibold text-gray-100">Comparativa con índice de referencia ({data.benchmark.symbol})</h2>{data.benchmark.status !== 'calculated' ? <Badge className="md:ml-auto" variant="outline">{data.benchmark.status === 'missing_benchmark' ? 'índice de referencia sin datos' : `solapamiento insuficiente (${data.benchmark.observations} días)`}</Badge> : null}</div>{data.benchmark.status === 'calculated' ? <section className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[['Cartera anualizada', pct(data.benchmark.portfolio_annualized)], [`${data.benchmark.symbol} anualizado`, pct(data.benchmark.benchmark_annualized)], ['Alpha', pct(data.benchmark.alpha_annualized)], ['Error de seguimiento', pct(data.benchmark.tracking_error)], ['Ratio de información', ratio(data.benchmark.information_ratio)], ['Observaciones', String(data.benchmark.observations)]].map(([label, value]) => <div className="rounded-xl border border-gray-800 bg-gray-900/40 p-4" key={label}><div className="text-xs font-semibold uppercase text-gray-500">{label}</div><div className="mt-2 text-xl font-semibold text-gray-100">{value}</div></div>)}</section> : <p className="mt-3 text-sm text-gray-400">La comparativa necesita la serie de precios de SPY actualizada y al menos 20 sesiones compartidas con la serie de retornos de la cartera.</p>}</section>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="flex flex-col gap-2 md:flex-row md:items-center"><h2 className="font-semibold text-gray-100">Contribución por posición</h2><Badge className="md:ml-auto" variant="outline">{data.ledger_contribution.coverage.positions === 0 ? 'sin posiciones' : `${data.ledger_contribution.coverage.with_contribution}/${data.ledger_contribution.coverage.positions} posiciones con contribución calculable`}</Badge></div><p className="mt-2 text-xs text-gray-500">Ganancias realizadas y no realizadas, más ingresos, reconstruidas desde el registro de transacciones{data.ledger_contribution.base_currency ? `, en ${data.ledger_contribution.base_currency}` : ''}. Contribución = valor final − valor inicial − neto invertido + ingresos. Los pesos firmados muestran ganadores por encima del 100 % y detractores en negativo.</p><div aria-label="Contribución por posición" className="scroll-affordance-x mt-4 overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}><table className="w-full min-w-[760px] text-left text-sm"><caption className="sr-only">Contribución a la P&amp;L de cada posición: valor inicial y final, neto invertido, ingresos, P&amp;L y peso sobre el horizonte</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">Ticker</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Valor inicial</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Valor final</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Neto invertido</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Ingresos</th><th className="border-b border-gray-800 py-2 text-right" scope="col">P&amp;L</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Peso</th></tr></thead><tbody>{data.ledger_contribution.positions.map((row) => <tr className="border-b border-gray-900" key={row.ticker}><th className="py-3 text-left text-sm font-semibold text-teal-300" scope="row">{row.ticker}</th><td className="py-3 text-right">{formatNumber(row.start_value, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{formatNumber(row.end_value, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{formatNumber(row.net_invested, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{formatNumber(row.income, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{row.contribution_pnl === null ? `${NA} (${LEDGER_REASON_LABELS[row.reason ?? ''] ?? 'sin datos suficientes'})` : formatNumber(row.contribution_pnl, { maximumFractionDigits: 0 })}</td><td className="py-3 text-right">{pct(row.contribution_share)}</td></tr>)}</tbody></table></div>{data.ledger_contribution.total_pnl !== null ? <p className="mt-3 text-sm text-gray-400">{data.ledger_contribution.coverage.with_contribution < data.ledger_contribution.coverage.positions ? `P&L de posiciones calculables (${data.ledger_contribution.coverage.with_contribution}/${data.ledger_contribution.coverage.positions})` : 'P&L total del horizonte'}: <span className="font-semibold text-gray-100">{formatNumber(data.ledger_contribution.total_pnl, { maximumFractionDigits: 0 })} {data.ledger_contribution.base_currency}</span></p> : <p className="mt-3 text-sm text-gray-400">P&L total del horizonte: sin datos. No hay registro de transacciones suficiente para reconstruir la contribución; el valor actual de la cartera no es una ganancia.</p>}</section>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><div className="flex flex-col gap-2 md:flex-row md:items-center"><h2 className="font-semibold text-gray-100">Atribución de retorno heurística</h2><Badge className="md:ml-auto" variant="outline">no es atribución contable</Badge></div><p className="mt-2 text-xs text-gray-500">Retorno de precio ajustado{data.attribution.period_start && data.attribution.period_end ? ` del ${formatMarketDate(data.attribution.period_start)} al ${formatMarketDate(data.attribution.period_end)}` : ` en un horizonte de hasta ${data.horizon_years} años`}, sin dividendos ni divisa. No es la G/P desde compra de Cartera.</p><div aria-label="Atribución de retorno heurística" className="scroll-affordance-x mt-4 overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}><table className="w-full min-w-[1050px] text-left text-sm"><caption className="sr-only">Atribución heurística del retorno por posición: peso, retorno de precio y contribución de cada componente de cartera</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">Ticker</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Peso sobre RV</th><th className="border-b border-gray-800 py-2 text-right" scope="col">Retorno de precio</th>{Object.keys(data.attribution.portfolio_components).map((key) => <th className="border-b border-gray-800 py-2 text-right" key={key} scope="col">{etiquetaComponenteAtribucion(key)}</th>)}</tr></thead><tbody>{data.attribution.positions.map((row) => <tr className="border-b border-gray-900" key={row.ticker}><th className="py-3 text-left text-sm font-semibold text-teal-300" scope="row">{row.ticker}{row.partial_history && row.period_start ? <Badge className="ml-2" variant="outline" title="Ventana medida mucho menor que la del panel; no entra en los totales agregados">historial parcial desde {formatMarketDate(row.period_start)}</Badge> : null}</th><td className="py-3 text-right">{pct(row.weight)}</td><td className="py-3 text-right" title={row.period_start && row.period_end ? `${formatMarketDate(row.period_start)} - ${formatMarketDate(row.period_end)}` : undefined}>{pct(row.total_return)}</td>{Object.keys(data.attribution.portfolio_components).map((key) => <td className="py-3 text-right text-gray-400" key={key}>{attributionCell(row.components[key] ?? null, key)}</td>)}</tr>)}</tbody></table></div>{data.attribution.excluded_partial_histories && data.attribution.excluded_partial_histories.length > 0 ? <p className="mt-3 text-xs text-amber-300/90">Con histórico parcial ({data.attribution.excluded_partial_histories.join(', ')}): su ventana medida cubre menos de la mitad de la del panel, así que se muestran por separado y no entran en los totales agregados.</p> : null}</section>
    <section className="rounded-xl border border-gray-800 bg-surface-1 p-5"><h2 className="font-semibold text-gray-100">Correlaciones de retornos</h2><p className="mt-2 text-xs text-gray-500">Correlación de Pearson entre retornos diarios en las sesiones en que ambas posiciones tienen precio. Con menos de {data.risk.correlation_min_observations} sesiones compartidas el coeficiente sería ruido con aspecto de medida: se muestra {NA} y el número de sesiones al pasar el cursor.</p><div aria-label="Correlaciones de retornos" className="scroll-affordance-x mt-4 overflow-x-auto [contain:layout_paint]" role="region" tabIndex={0}><table className="text-sm"><caption className="sr-only">Matriz de correlaciones de los retornos diarios de cada posición de la cartera</caption><thead><tr><th className="p-2" scope="col"><span className="sr-only">Variable</span></th>{tickers.map((ticker) => <th className="p-2 text-gray-400" key={ticker} scope="col">{ticker}</th>)}</tr></thead><tbody>{tickers.map((left) => <tr key={left}><th className="p-2 text-left text-sm font-normal text-gray-400" scope="row">{left}</th>{tickers.map((right) => { const correlation = data.risk.correlations[left]?.[right]; const observations = data.risk.correlation_observations?.[left]?.[right] ?? 0; const insufficient = left !== right && observations < data.risk.correlation_min_observations; const title = left === right ? undefined : insufficient ? `Histórico insuficiente: ${observations} sesiones compartidas (mínimo ${data.risk.correlation_min_observations})` : `${observations} sesiones compartidas`; return <td className="min-w-16 border border-gray-900 p-2 text-center text-gray-300" key={right} title={title} style={{ backgroundColor: correlation === null || correlation === undefined ? 'transparent' : correlation >= 0 ? `rgb(13 148 136 / ${Math.abs(correlation) * 0.35})` : `rgb(239 68 68 / ${Math.abs(correlation) * 0.35})` }}>{correlation === null || correlation === undefined ? NA : formatNumber(correlation, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>; })}</tr>)}</tbody></table></div></section>
  </main>;
}
