'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { AutoscaleInfo, IChartApi, IPriceLine, ISeriesApi, ISeriesMarkersPluginApi, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { isValidCurrencyCode, type Formatters } from '@/lib/format';
import { useFormat, useT } from '@/lib/i18n/client';
import { intlLocale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';
import { getCompanyChartHistory, type CompanyChartHistory, type CompanyChartBar } from '@/lib/actions/company-chart.actions';
import MobileCollapse from '@/components/ui/mobile-collapse';
import { TRADINGVIEW_URL } from '@/lib/market/candles';
import { CHART_RANGES, type CompanyChartRange } from '@/lib/market/chart-ranges';
import { normalizeChartPriceUnits } from '@/lib/market/chart-price-units';
import { adx, cleanBars, dailyPivots, fibonacci, rangeBars, sma, structure } from '@/lib/market/technical';
import { getChartEvents, type ChartEvents } from '@/lib/actions/price-events.actions';
import { availableIndicators, barsSince, detectMovements, eventsInRange, movementEvents, indicatorSeries, INDICATOR_KEYS, markersByDay, volumeSpikeFlags, type IndicatorKind, type PriceEventKind } from '@/lib/market/price-events';
import { PriceEventsPanel } from '@/components/research/PriceEventsPanel';

function price(value: number, currency: string | null, { formatMoney, formatNumber }: Pick<Formatters, 'formatMoney' | 'formatNumber'>) {
    return isValidCurrencyCode(currency) ? formatMoney(value, currency) : formatNumber(value);
}

/** Etiqueta visible de cada rango (el valor interno sigue en español: «1A», «Máx»). */
const RANGE_KEYS: Record<CompanyChartRange, TranslationKey> = {
    '1D': 'research.chart.range1D', '5D': 'research.chart.range5D', '1M': 'research.chart.range1M', '6M': 'research.chart.range6M',
    YTD: 'research.chart.rangeYTD', '1A': 'research.chart.range1A', '5A': 'research.chart.range5A', 'Máx': 'research.chart.rangeMax',
};

/** structure() devuelve la palabra española de referencia; aquí se traduce al mostrarla. */
const TREND_KEYS: Record<ReturnType<typeof structure>, TranslationKey> = {
    Alcista: 'research.chart.trendUp', Bajista: 'research.chart.trendDown', Mixta: 'research.chart.trendMixed', 'Sin datos': 'research.chart.noData',
};

function sideKey(close: number, average: number): 'above' | 'below' | 'at' {
    return close > average ? 'above' : close < average ? 'below' : 'at';
}

function readingLines(t: TranslateFn, trend: ReturnType<typeof structure>) {
    return trend === 'Alcista' ? t('research.chart.structureUp') : trend === 'Bajista' ? t('research.chart.structureDown') : t('research.chart.structureMixed');
}

export default function CompanyTechnicalChart({ snapshot }: { snapshot: CompanyMarketSnapshot }) {
    const t = useT();
    const fmt = useFormat();
    const { formatMarketDate, formatNumber } = fmt;
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
    const [sinceBuy, setSinceBuy] = useState(false);
    const [chartEvents, setChartEvents] = useState<{ key: string; data: ChartEvents } | null>(null);
    const rangeVisible = useMemo(() => needsRemote ? remotePrices.bars : rangeBars(bars, range as '1M' | '6M' | 'YTD' | '1A'), [bars, range, needsRemote, remotePrices]);
    const visible = useMemo(() => sinceBuy ? barsSince(rangeVisible, chartEvents?.data.firstBuyDate) : rangeVisible, [rangeVisible, sinceBuy, chartEvents]);
    const visibleCurrency = needsRemote ? remotePrices.currency : daily.currency;
    const hourly = range === '1D' || range === '5D';
    // «Precio y eventos»: eventos guardados del tramo visible (solo base de datos) sobre las mismas velas.
    const firstDay = visible[0]?.date.slice(0, 10);
    const lastDay = visible.at(-1)?.date.slice(0, 10);
    const eventsKey = firstDay && lastDay ? `${snapshot.ticker}|${firstDay}|${lastDay}` : null;
    useEffect(() => {
        if (!eventsKey || !firstDay || !lastDay) return;
        let cancelled = false;
        getChartEvents(snapshot.ticker, firstDay, lastDay).then((data) => {
            if (!cancelled) setChartEvents({ key: eventsKey, data });
        }).catch(() => undefined);
        return () => { cancelled = true; };
    }, [eventsKey, snapshot.ticker, firstDay, lastDay]);
    const eventData = chartEvents?.data ?? null;
    const target = eventData && eventData.target != null && (!eventData.targetCurrency || eventData.targetCurrency === visibleCurrency) ? eventData.target : null;
    const averageCost = eventData?.averageCost ?? null;
    const indicators = availableIndicators({ target, averageCost });
    const [indicatorChoice, setIndicatorChoice] = useState<IndicatorKind | null>(null);
    const indicator: IndicatorKind = indicatorChoice && indicators.includes(indicatorChoice) ? indicatorChoice : indicators[0];
    const indicatorValues = useMemo(() => hourly ? [] : indicatorSeries(visible, indicator, { target, averageCost }), [visible, indicator, target, averageCost, hourly]);
    const spikes = useMemo(() => volumeSpikeFlags(visible), [visible]);
    const [hiddenKinds, setHiddenKinds] = useState<ReadonlySet<PriceEventKind>>(() => new Set());
    const [focusDate, setFocusDate] = useState<string | null>(null);
    const storedEvents = useMemo(() => eventsInRange(eventData?.events ?? [], firstDay, lastDay), [eventData, firstDay, lastDay]);
    // «¿Por qué se movió?»: los días de movimiento fuerte se listan con lo que pasó alrededor.
    const rangeEvents = useMemo(() => hourly ? storedEvents : eventsInRange([...storedEvents, ...movementEvents(detectMovements(visible), storedEvents, t, fmt.locale)], firstDay, lastDay), [storedEvents, visible, hourly, firstDay, lastDay, t, fmt.locale]);
    const markers = useMemo(() => hourly ? [] : markersByDay(rangeEvents, hiddenKinds), [rangeEvents, hiddenKinds, hourly]);
    const priceLines = useMemo(() => [
        ...(target != null ? [{ label: t('research.chart.lineTarget'), price: target, color: '#a78bfa' }] : []),
        ...(averageCost != null ? [{ label: t('research.chart.lineAverageCost'), price: averageCost, color: '#fbbf24' }] : []),
    ], [target, averageCost, t]);

    const levels = useMemo(() => dailyPivots(bars), [bars]);
    const fib = useMemo(() => fibonacci(visible), [visible]);
    const trend = structure(bars);
    const average = sma(bars, 50);
    const previousAverage = sma(bars.slice(0, -1), 50);
    const strength = adx(bars.slice(-100));
    const last = bars.at(-1);
    const shortTerm = !last || average == null ? t('research.chart.noData') : { above: t('research.chart.aboveSma50'), below: t('research.chart.belowSma50'), at: t('research.chart.atSma50') }[sideKey(last.close, average)];
    const slope = average == null || previousAverage == null ? null : average > previousAverage ? t('research.chart.sma50Rising') : average < previousAverage ? t('research.chart.sma50Falling') : t('research.chart.sma50Flat');
    const chartLevels = daily.currency === visibleCurrency ? levels : [];
    return (
        <section className="min-w-0 overflow-hidden rounded-xl border border-gray-800 bg-surface-1" data-testid="company-technical-chart" aria-label={t('research.chart.sectionAria')}>
            <div className="grid min-w-0 xl:grid-cols-[minmax(0,1fr)_340px]">
                <div className="min-w-0 p-3 sm:p-5">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <h2 className="text-sm font-semibold text-gray-200">{t('research.chart.price')}</h2>
                        <span className="text-xs text-gray-500">{hourly ? t('research.chart.hourlyUtc') : t('research.chart.daily')}{visible.at(-1) ? ` · ${formatMarketDate(visible.at(-1)!.date)}` : ''}</span>
                    </div>
                    {needsRemote && requestState === 'loading' ? <div className="grid h-[280px] place-items-center text-xs text-gray-500 sm:h-[360px]" role="status">{t('research.chart.loadingRange', { range: t(RANGE_KEYS[range]) })}</div> : needsRemote && requestState === 'error' ? <div className="grid h-[280px] place-items-center text-sm text-gray-500 sm:h-[360px]" role="alert">{t('research.chart.rangeError')}</div> : <PriceCanvas bars={visible} levels={chartLevels} currency={visibleCurrency} hourly={hourly} indicator={indicatorValues} indicatorLabel={t(INDICATOR_KEYS[indicator])} spikes={spikes} markers={markers} priceLines={priceLines} focusDate={focusDate} />}
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex w-full flex-wrap gap-1 sm:w-auto" aria-label={t('research.chart.rangeAria')}>
                            {CHART_RANGES.map((value) => <button type="button" key={value} disabled={range === value && requestState !== 'error'} aria-pressed={range === value} className={`min-h-11 min-w-11 rounded-md px-1 text-[11px] transition sm:px-3 sm:text-xs ${range === value ? 'bg-teal-400/10 font-semibold text-teal-300' : 'text-gray-500 hover:bg-gray-800 hover:text-gray-200'}`} onClick={() => { if (range === value) setRetry((count) => count + 1); setRequestState(value === '1D' || value === '5D' || value === '5A' || value === 'Máx' ? 'loading' : 'ready'); setSinceBuy(false); setRange(value); }}>{t(RANGE_KEYS[value])}</button>)}
                            {eventData?.firstBuyDate ? <button type="button" aria-pressed={sinceBuy} className={`min-h-11 rounded-md px-2 text-[11px] transition sm:px-3 sm:text-xs ${sinceBuy ? 'bg-teal-400/10 font-semibold text-teal-300' : 'text-gray-500 hover:bg-gray-800 hover:text-gray-200'}`} onClick={() => { setSinceBuy(true); if (range !== 'Máx') { setRequestState('loading'); setRange('Máx'); } }}>{t('research.chart.sinceBuy')}</button> : null}
                        </div>
                        <a href={TRADINGVIEW_URL} target="_blank" rel="noreferrer" className="inline-flex min-h-11 min-w-11 items-center text-[10px] text-gray-500 underline">TradingView</a>
                    </div>
                    {visible.length > 0 ? <p className="mt-1 text-[11px] text-gray-500">{formatMarketDate(visible[0].date)} – {formatMarketDate(visible.at(-1)!.date)} · {hourly ? t('research.chart.hourlyBars', { count: visible.length }) : t('research.chart.sessions', { count: visible.length })}{range === 'Máx' ? ` · ${t('research.chart.providerMax')}` : ''}{hourly ? ` · ${t('research.chart.lastBarWindow')}` : ''}</p> : null}
                    <PriceEventsPanel
                        events={rangeEvents}
                        hiddenKinds={hiddenKinds}
                        onToggleKind={(kind) => setHiddenKinds((current) => { const next = new Set(current); if (next.has(kind)) next.delete(kind); else next.add(kind); return next; })}
                        onFocus={setFocusDate}
                        indicators={indicators}
                        indicator={indicator}
                        onIndicator={setIndicatorChoice}
                        hourly={hourly}
                        t={t}
                        formatMarketDate={formatMarketDate}
                    />
                </div>
                <MobileCollapse title={t('research.chart.reading')}><aside className="min-w-0 border-t border-gray-800 p-4 xl:border-l xl:border-t-0" data-testid="technical-reading">
                    <h2 className="hidden text-base font-semibold text-gray-100 md:block">{t('research.chart.reading')}</h2>
                    <div id={`technical-panel-${snapshot.ticker}`} className="mt-3 space-y-4 text-xs text-gray-400">
                        {last ? <p className="text-[11px] text-gray-500">{t('research.chart.observedUntil', { date: formatMarketDate(last.date) })}</p> : null}
                        {last ? <p className="text-[11px] text-gray-500">{t('research.chart.unconfirmedClose')}</p> : null}
                        <>
                            <dl className="grid grid-cols-3 gap-2">
                                <Metric label={t('research.chart.structure')} value={t(TREND_KEYS[trend])} detail={t('research.chart.structureDetail')} />
                                <Metric label={t('research.chart.shortTerm')} value={shortTerm} detail={slope ?? t('research.chart.needs50Sessions')} />
                                <Metric label={t('research.chart.strength')} value={strength == null ? t('research.chart.noData') : `${formatNumber(strength, { maximumFractionDigits: 1 })} ADX`} detail={strength == null ? t('research.chart.needsOhlc') : strength >= 25 ? t('research.chart.strongTrend') : t('research.chart.weakTrend')} />
                            </dl>
                            <div className="space-y-2 border-t border-gray-800 pt-3 leading-5">
                                {trend !== 'Sin datos' ? <p>{readingLines(t, trend)}</p> : <p>{t('research.chart.structureNoData')}</p>}
                                {average != null && last ? <p>{{ above: t('research.chart.lastCloseAbove', { price: price(last.close, daily.currency, fmt), average: price(average, daily.currency, fmt) }), below: t('research.chart.lastCloseBelow', { price: price(last.close, daily.currency, fmt), average: price(average, daily.currency, fmt) }), at: t('research.chart.lastCloseAt', { price: price(last.close, daily.currency, fmt), average: price(average, daily.currency, fmt) }) }[sideKey(last.close, average)]}</p> : null}
                                {strength != null ? <p>{strength >= 25 ? t('research.chart.adxStrong', { value: formatNumber(strength, { maximumFractionDigits: 1 }) }) : t('research.chart.adxWeak', { value: formatNumber(strength, { maximumFractionDigits: 1 }) })}</p> : null}
                            </div>
                        </>
                        <div>
                            <h3 className="mb-2 font-medium text-gray-200">{t('research.chart.fibTitle', { range: t(RANGE_KEYS[range]) })}</h3>
                            {fib.length ? <dl className="space-y-3">{fib.map((level) => <div key={level.ratio} className="flex justify-between border-b border-gray-800 pb-2"><dt>{t('research.chart.fibRatio', { value: formatNumber(level.ratio * 100) })}</dt><dd className="tabular-nums text-gray-200">{price(level.price, visibleCurrency, fmt)}</dd></div>)}</dl> : <p>{t('research.chart.fibNoData')}</p>}
                            <p className="mt-3 text-[11px] text-gray-500">{t('research.chart.fibNote')}</p>
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

type CanvasMarker = { date: string; text: string; color: string; count: number };
type CanvasPriceLine = { label: string; price: number; color: string };

function PriceCanvas({ bars, levels, currency, hourly = false, indicator = [], indicatorLabel = '', spikes = [], markers = [], priceLines = [], focusDate = null }: {
    bars: CompanyChartBar[];
    hourly?: boolean;
    levels: { label: string; price: number; kind: string }[];
    currency: string | null;
    indicator?: Array<{ date: string; value: number }>;
    indicatorLabel?: string;
    spikes?: boolean[];
    markers?: CanvasMarker[];
    priceLines?: CanvasPriceLine[];
    focusDate?: string | null;
}) {
    const t = useT();
    const fmt = useFormat();
    const container = useRef<HTMLDivElement>(null);
    const engine = useRef<{
        chart: IChartApi;
        line: ISeriesApi<'Area', Time>;
        indicator: ISeriesApi<'Line', Time>;
        volume: ISeriesApi<'Histogram', Time>;
        markers: ISeriesMarkersPluginApi<Time>;
        levels: IPriceLine[];
        dashed: IPriceLine[];
        dashedStyle: number;
    } | null>(null);
    const percent = (value: string) => t('research.chart.fibRatio', { value });
    const latest = useRef({ bars, levels, currency, fmt, percent });
    // Sincroniza el ref tras cada render (react-hooks/refs prohibe escribirlo
    // durante el render). Declarado antes del resto de efectos: se ejecuta primero.
    useEffect(() => {
        latest.current = { bars, levels, currency, fmt, percent };
    });
    const [ready, setReady] = useState(false);
    const [error, setError] = useState(false);
    useEffect(() => {
        let disposed = false;
        let chart: IChartApi | null = null;
        (async () => {
            try {
                const { createChart, createSeriesMarkers, AreaSeries, HistogramSeries, LineSeries, LineStyle, ColorType } = await import('lightweight-charts');
                if (disposed || !container.current) return;
                chart = createChart(container.current, {
                    autoSize: true,
                    layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a', fontSize: 11, attributionLogo: true, panes: { separatorColor: '#27272a' } },
                    grid: { vertLines: { visible: false }, horzLines: { color: '#27272a' } },
                    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
                    timeScale: { borderVisible: false, rightOffset: 6 },
                    localization: { locale: intlLocale(latest.current.fmt.locale), priceFormatter: (value: number) => price(value, latest.current.currency, latest.current.fmt) },
                });
                const line = chart.addSeries(AreaSeries, { lineColor: '#5eead4', topColor: 'rgba(94,234,212,0.12)', bottomColor: 'rgba(94,234,212,0)', lineWidth: 2, priceLineVisible: false });
                // Tres paneles con el mismo eje de tiempo: precio, indicador y volumen.
                const indicatorSeriesApi = chart.addSeries(LineSeries, { color: '#a78bfa', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: 'custom', formatter: (value: number) => latest.current.percent(latest.current.fmt.formatNumber(value, { maximumFractionDigits: 1 })), minMove: 0.01 } }, 1);
                const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false }, 2);
                const panes = chart.panes();
                panes[0]?.setStretchFactor(3);
                panes[1]?.setStretchFactor(1);
                panes[2]?.setStretchFactor(1);
                const markerApi = createSeriesMarkers(line, []);
                engine.current = { chart, line, indicator: indicatorSeriesApi, volume, markers: markerApi, levels: [], dashed: [], dashedStyle: LineStyle.Dashed };
                if (!disposed) setReady(true);
            } catch { if (!disposed) setError(true); }
        })();
        return () => { disposed = true; chart?.remove(); engine.current = null; };
    }, []);
    useEffect(() => {
        const current = engine.current;
        if (!ready || !current) return;
        current.chart.timeScale().applyOptions({ timeVisible: hourly });
        const extra = [...levels.map((level) => level.price), ...priceLines.map((line) => line.price)];
        current.line.applyOptions({ autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
            const info = original();
            if (!info || !info.priceRange || !extra.length) return info;
            return { ...info, priceRange: { minValue: Math.min(info.priceRange.minValue, ...extra), maxValue: Math.max(info.priceRange.maxValue, ...extra) } };
        } });
        const timeOf = (bar: CompanyChartBar) => (bar.timestamp ? bar.timestamp as UTCTimestamp : bar.date) as Time;
        current.line.setData(bars.map((bar) => ({ time: timeOf(bar), value: bar.close })));
        current.volume.setData(bars.flatMap((bar, index) => typeof bar.volume === 'number' && Number.isFinite(bar.volume) && bar.volume >= 0
            ? [{ time: timeOf(bar), value: bar.volume, color: spikes[index] ? 'rgba(251,113,133,0.85)' : bar.close >= (bars[index - 1]?.close ?? bar.close) ? 'rgba(45,212,191,0.35)' : 'rgba(248,113,113,0.35)' }]
            : []));
        current.indicator.setData(hourly ? [] : indicator.map((point) => ({ time: point.date as Time, value: point.value })));
        current.indicator.applyOptions({ title: indicatorLabel });
        const known = new Set(bars.map((bar) => bar.date));
        const seriesMarkers: SeriesMarker<Time>[] = hourly ? [] : markers.filter((marker) => known.has(marker.date)).map((marker) => ({ time: marker.date as Time, position: 'aboveBar', shape: 'circle', color: marker.color, text: marker.text, size: marker.count > 1 ? 1.4 : 1 }));
        current.markers.setMarkers(seriesMarkers);
        // En movil las etiquetas de precio de R/S taparian las del eje; los niveles exactos van en la tabla de pivotes.
        const wide = window.matchMedia('(min-width: 640px)').matches;
        for (const level of current.levels) current.line.removePriceLine(level);
        current.levels = levels.map((level) => current.line.createPriceLine({ price: level.price, title: level.label, color: level.kind === 'support' ? '#2dd4bf' : level.kind === 'resistance' ? '#fb7185' : '#a78bfa', lineWidth: 1, lineStyle: 2, axisLabelVisible: wide }));
        for (const dashed of current.dashed) current.line.removePriceLine(dashed);
        current.dashed = priceLines.map((line) => current.line.createPriceLine({ price: line.price, title: line.label, color: line.color, lineWidth: 1, lineStyle: current.dashedStyle, axisLabelVisible: true }));
        current.chart.timeScale().fitContent();
    }, [ready, bars, levels, hourly, indicator, indicatorLabel, spikes, markers, priceLines]);
    useEffect(() => {
        const current = engine.current;
        if (!ready || !current || !focusDate) return;
        const bar = bars.find((item) => item.date.slice(0, 10) === focusDate);
        if (bar) current.chart.setCrosshairPosition(bar.close, (bar.timestamp ? bar.timestamp as UTCTimestamp : bar.date) as Time, current.line);
    }, [ready, focusDate, bars]);
    return <div className="relative">
        <div ref={container} className="h-[380px] w-full sm:h-[480px]" role="figure" aria-label={bars.length ? t('research.chart.canvasAria', { from: fmt.formatMarketDate(bars[0].date), to: fmt.formatMarketDate(bars.at(-1)!.date) }) : t('research.chart.canvasAriaEmpty')} data-testid="technical-price-canvas" />
        {error || bars.length < 2 ? <p role="status" className="absolute inset-0 grid place-items-center bg-surface-1 text-sm text-gray-500">{error ? t('research.chart.chartError') : t('research.chart.notEnoughData')}</p> : !ready ? <p role="status" className="absolute inset-0 grid animate-pulse place-items-center text-xs text-gray-500">{t('research.chart.loadingChart')}</p> : null}
    </div>;
}
