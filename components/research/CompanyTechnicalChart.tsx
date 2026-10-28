'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { AutoscaleInfo, IChartApi, IPriceLine, ISeriesApi, Time, UTCTimestamp } from 'lightweight-charts';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { formatMarketDate, formatMoney, formatNumber, isValidCurrencyCode } from '@/lib/format';
import { getCompanyChartHistory, type CompanyChartHistory, type CompanyChartBar } from '@/lib/actions/company-chart.actions';
import MobileCollapse from '@/components/ui/mobile-collapse';
import { TRADINGVIEW_URL } from '@/lib/market/candles';
import { CHART_RANGES, type CompanyChartRange } from '@/lib/market/chart-ranges';
import { normalizeChartPriceUnits } from '@/lib/market/chart-price-units';
import { adx, cleanBars, dailyPivots, fibonacci, rangeBars, sma, structure } from '@/lib/market/technical';

function price(value: number, currency: string | null) {
    return isValidCurrencyCode(currency) ? formatMoney(value, currency) : formatNumber(value);
}

export default function CompanyTechnicalChart({ snapshot }: { snapshot: CompanyMarketSnapshot }) {
    const [retry, setRetry] = useState(0);
    const [range, setRange] = useState<CompanyChartRange>('1M');
    const daily = useMemo(() => normalizeChartPriceUnits(cleanBars(snapshot.history), { ticker: snapshot.ticker, currency: snapshot.currency, candleCurrency: snapshot.historyCurrency }), [snapshot.history, snapshot.ticker, snapshot.currency, snapshot.historyCurrency]);
    const bars = daily.bars;
    const [remote, setRemote] = useState<{ range: CompanyChartRange; data: CompanyChartHistory } | null>(null);
    const [requestState, setRequestState] = useState<'loading' | 'ready' | 'error'>('ready');
    const needsRemote = range === '1D' || range === '5D' || range === '5A' || range === 'Máx';
    useEffect(() => {
        if (!needsRemote) return;
        let cancelled = false;
        getCompanyChartHistory(snapshot.ticker, range).then((data) => {
            if (cancelled) return;
            setRemote({ range, data }); setRequestState('ready');
        }).catch(() => { if (!cancelled) setRequestState('error'); });
        return () => { cancelled = true; };
    }, [snapshot.ticker, range, needsRemote, retry]);
    const remotePrices = useMemo(() => normalizeChartPriceUnits(remote?.range === range ? remote.data.bars : [], { ticker: snapshot.ticker, currency: snapshot.currency, candleCurrency: remote?.range === range ? remote.data.currency : null }), [remote, range, snapshot.ticker, snapshot.currency]);
    const visible = useMemo(() => needsRemote ? remotePrices.bars : rangeBars(bars, range as '1M' | '6M' | 'YTD' | '1A'), [bars, range, needsRemote, remotePrices]);
    const visibleCurrency = needsRemote ? remotePrices.currency : daily.currency;
    const hourly = range === '1D' || range === '5D';
    const historySource = needsRemote ? remote?.range === range ? remote.data.source : null : snapshot.historySource;

    const levels = useMemo(() => dailyPivots(bars), [bars]);
    const fib = useMemo(() => fibonacci(visible), [visible]);
    const trend = structure(bars);
    const average = sma(bars, 50);
    const previousAverage = sma(bars.slice(0, -1), 50);
    const strength = adx(bars.slice(-100));
    const last = bars.at(-1);
    const shortTerm = !last || average == null ? 'Sin datos' : last.close > average ? 'Sobre SMA50' : last.close < average ? 'Bajo SMA50' : 'En SMA50';
    const slope = average == null || previousAverage == null ? null : average > previousAverage ? 'sube' : average < previousAverage ? 'baja' : 'plana';
    const chartLevels = daily.currency === visibleCurrency ? levels : [];
    return (
        <section className="min-w-0 overflow-hidden rounded-xl border border-gray-800 bg-surface-1" data-testid="company-technical-chart" aria-label="Precio y lectura técnica">
            <div className="grid min-w-0 xl:grid-cols-[minmax(0,1fr)_340px]">
                <div className="min-w-0 p-3 sm:p-5">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <h2 className="text-sm font-semibold text-gray-200">Precio</h2>
                        <span className="text-xs text-gray-500">{hourly ? 'Horario (UTC)' : 'Diario'} · {historySource || 'Fuente no disponible'}{visible.at(-1) ? ` · ${formatMarketDate(visible.at(-1)!.date)}` : ''}</span>
                    </div>
                    {needsRemote && requestState === 'loading' ? <div className="grid h-[280px] place-items-center text-xs text-gray-500 sm:h-[360px]" role="status">Cargando rango {range}</div> : needsRemote && requestState === 'error' ? <div className="grid h-[280px] place-items-center text-sm text-gray-500 sm:h-[360px]" role="alert">No se pudo cargar este rango</div> : <PriceCanvas bars={visible} levels={chartLevels} currency={visibleCurrency} hourly={hourly} />}
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex w-full flex-wrap gap-1 sm:w-auto" aria-label="Rango del gráfico">
                            {CHART_RANGES.map((value) => <button type="button" key={value} disabled={range === value && requestState !== 'error'} aria-pressed={range === value} className={`min-h-11 min-w-11 rounded-md px-1 text-[11px] transition sm:px-3 sm:text-xs ${range === value ? 'bg-teal-400/10 font-semibold text-teal-300' : 'text-gray-500 hover:bg-gray-800 hover:text-gray-200'}`} onClick={() => { if (range === value) setRetry((count) => count + 1); setRequestState(value === '1D' || value === '5D' || value === '5A' || value === 'Máx' ? 'loading' : 'ready'); setRange(value); }}>{value}</button>)}
                        </div>
                        <a href={TRADINGVIEW_URL} target="_blank" rel="noreferrer" className="inline-flex min-h-11 min-w-11 items-center text-[10px] text-gray-500 underline">TradingView</a>
                    </div>
                    {visible.length > 0 ? <p className="mt-1 text-[11px] text-gray-500">{formatMarketDate(visible[0].date)} – {formatMarketDate(visible.at(-1)!.date)} · {visible.length} {hourly ? 'velas horarias' : 'sesiones'}{range === 'Máx' ? ' · Máximo disponible del proveedor' : ''}{hourly ? ' · Ventana sobre la última vela disponible' : ''}</p> : null}
                </div>
                <MobileCollapse title="Lectura técnica"><aside className="min-w-0 border-t border-gray-800 p-4 xl:border-l xl:border-t-0" data-testid="technical-reading">
                    <h2 className="hidden text-base font-semibold text-gray-100 md:block">Lectura técnica</h2>
                    <div id={`technical-panel-${snapshot.ticker}`} className="mt-3 space-y-4 text-xs text-gray-400">
                        {last ? <p className="text-[11px] text-gray-500">Precios diarios observados hasta {formatMarketDate(last.date)}</p> : null}
                        {last ? <p className="text-[11px] text-gray-500">El proveedor no confirma el cierre de la última vela: puede estar en curso. La lectura técnica y los niveles son provisionales.</p> : null}
                        <>
                            <dl className="grid grid-cols-3 gap-2">
                                <Metric label="Estructura" value={trend} detail="Dos bloques de 10 sesiones" />
                                <Metric label="Corto plazo" value={shortTerm} detail={slope ? `SMA50 ${slope}` : '50 sesiones necesarias'} />
                                <Metric label="Fuerza" value={strength == null ? 'Sin datos' : `${formatNumber(strength, { maximumFractionDigits: 1 })} ADX`} detail={strength == null ? 'OHLC completo necesario' : strength >= 25 ? 'Tendencia fuerte' : 'Tendencia débil'} />
                            </dl>
                            <div className="space-y-2 border-t border-gray-800 pt-3 leading-5">
                                {trend !== 'Sin datos' ? <p>{trend === 'Alcista' ? 'Máximos y mínimos crecientes' : trend === 'Bajista' ? 'Máximos y mínimos decrecientes' : 'Máximos y mínimos sin dirección conjunta'} entre los dos últimos bloques de 10 sesiones.</p> : <p>Estructura: sin datos OHLC suficientes.</p>}
                                {average != null && last ? <p>Último precio diario {price(last.close, daily.currency)}, {last.close > average ? 'sobre' : last.close < average ? 'bajo' : 'en'} la media de 50 sesiones ({price(average, daily.currency)}).</p> : null}
                                {strength != null ? <p>ADX14 {formatNumber(strength, { maximumFractionDigits: 1 })}: {strength >= 25 ? 'fuerza de tendencia' : 'sin fuerza de tendencia confirmada'}. No indica dirección.</p> : null}
                            </div>
                        </>
                        <div>
                            <h3 className="mb-2 font-medium text-gray-200">Pivotes de referencia de la última vela{last ? ` · ${formatMarketDate(last.date)}` : ''}</h3>
                            {levels.length ? <dl className="space-y-2">{levels.map((level) => <div key={level.label} className="flex justify-between border-b border-gray-800 pb-1.5"><dt className={level.kind === 'support' ? 'text-teal-300' : 'text-red-300'}>{level.label}</dt><dd className="tabular-nums text-gray-200">{price(level.price, daily.currency)}</dd></div>)}</dl> : <p>Sin datos OHLC para calcular niveles.</p>}
                            <p className="mt-2 text-[11px] text-gray-500">Calculados con máximo, mínimo y último precio de la vela; pueden cambiar si sigue en curso. No son giros confirmados.</p>
                        </div>
                        <div>
                            <h3 className="mb-2 font-medium text-gray-200">Niveles de retroceso ({range})</h3>
                            {fib.length ? <dl className="space-y-3">{fib.map((level) => <div key={level.ratio} className="flex justify-between border-b border-gray-800 pb-2"><dt>{formatNumber(level.ratio * 100)} %</dt><dd className="tabular-nums text-gray-200">{price(level.price, visibleCurrency)}</dd></div>)}</dl> : <p>Sin datos OHLC para Fibonacci.</p>}
                            <p className="mt-3 text-[11px] text-gray-500">Desde el máximo al mínimo del tramo visible.</p>
                        </div>
                    </div>
                </aside></MobileCollapse>
            </div>
        </section>
    );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
    return <div className="min-w-0 rounded-lg bg-gray-900/60 p-2"><dt className="text-[10px] text-gray-500">{label}</dt><dd className="mt-1 break-words text-xs font-semibold text-gray-200">{value}</dd><dd className="mt-1 text-[10px] leading-4 text-gray-500">{detail}</dd></div>;
}

function PriceCanvas({ bars, levels, currency, hourly = false }: { bars: CompanyChartBar[]; hourly?: boolean; levels: { label: string; price: number; kind: string }[]; currency: string | null }) {
    const container = useRef<HTMLDivElement>(null);
    const engine = useRef<{ chart: IChartApi; line: ISeriesApi<'Area', Time>; volume: ISeriesApi<'Histogram', Time>; levels: IPriceLine[] } | null>(null);
    const latest = useRef({ bars, levels, currency });
    // Sincroniza el ref tras cada render (react-hooks/refs prohibe escribirlo
    // durante el render). Declarado antes del resto de efectos: se ejecuta primero.
    useEffect(() => {
        latest.current = { bars, levels, currency };
    });
    const [ready, setReady] = useState(false);
    const [error, setError] = useState(false);
    useEffect(() => {
        let disposed = false;
        let chart: IChartApi | null = null;
        (async () => {
            try {
                const { createChart, AreaSeries, HistogramSeries, ColorType } = await import('lightweight-charts');
                if (disposed || !container.current) return;
                chart = createChart(container.current, {
                    autoSize: true,
                    layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a', fontSize: 11, attributionLogo: true },
                    grid: { vertLines: { visible: false }, horzLines: { color: '#27272a' } },
                    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.18, bottom: 0.22 } },
                    timeScale: { borderVisible: false, rightOffset: 6 },
                    localization: { locale: 'es-ES', priceFormatter: (value: number) => price(value, latest.current.currency) },
                });
                const line = chart.addSeries(AreaSeries, { lineColor: '#5eead4', topColor: 'rgba(94,234,212,0.12)', bottomColor: 'rgba(94,234,212,0)', lineWidth: 2, priceLineVisible: false });
                const volume = chart.addSeries(HistogramSeries, { priceScaleId: 'volume', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
                chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 }, visible: false });
                engine.current = { chart, line, volume, levels: [] };
                if (!disposed) setReady(true);
            } catch { if (!disposed) setError(true); }
        })();
        return () => { disposed = true; chart?.remove(); engine.current = null; };
    }, []);
    useEffect(() => {
        const current = engine.current;
        if (!ready || !current) return;
        current.chart.timeScale().applyOptions({ timeVisible: hourly });
        current.line.applyOptions({ autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
            const info = original();
            if (!info || !info.priceRange || !levels.length) return info;
            return { ...info, priceRange: { minValue: Math.min(info.priceRange.minValue, ...levels.map((level) => level.price)), maxValue: Math.max(info.priceRange.maxValue, ...levels.map((level) => level.price)) } };
        } });
        current.line.setData(bars.map((bar) => ({ time: bar.timestamp ? bar.timestamp as UTCTimestamp : bar.date, value: bar.close })));
        current.volume.setData(bars.filter((bar) => typeof bar.volume === 'number' && Number.isFinite(bar.volume) && bar.volume >= 0).map((bar) => ({ time: bar.timestamp ? bar.timestamp as UTCTimestamp : bar.date, value: bar.volume!, color: 'rgba(113,113,122,0.3)' })));
        // En movil las etiquetas de precio de R/S taparian las del eje; los niveles exactos van en la tabla de pivotes.
        const wide = window.matchMedia('(min-width: 640px)').matches;
        for (const level of current.levels) current.line.removePriceLine(level);
        current.levels = levels.map((level) => current.line.createPriceLine({ price: level.price, title: level.label, color: level.kind === 'support' ? '#2dd4bf' : level.kind === 'resistance' ? '#fb7185' : '#a78bfa', lineWidth: 1, lineStyle: 2, axisLabelVisible: wide }));
        current.chart.timeScale().fitContent();
    }, [ready, bars, levels, hourly]);
    return <div className="relative">
        <div ref={container} className="h-[280px] w-full sm:h-[360px]" role="figure" aria-label={`Evolución del precio${bars.length ? ` del ${formatMarketDate(bars[0].date)} al ${formatMarketDate(bars.at(-1)!.date)}` : ': sin datos'}`} data-testid="technical-price-canvas" />
        {error || bars.length < 2 ? <p role="status" className="absolute inset-0 grid place-items-center bg-surface-1 text-sm text-gray-500">{error ? 'No se pudo cargar el gráfico' : 'Sin datos suficientes para este rango'}</p> : !ready ? <p role="status" className="absolute inset-0 grid animate-pulse place-items-center text-xs text-gray-500">Cargando gráfico</p> : null}
    </div>;
}
