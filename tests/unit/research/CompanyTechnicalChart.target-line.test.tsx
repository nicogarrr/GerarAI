import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { LocaleProvider } from '@/lib/i18n/client';

// Encargo del dueño (3-nov-2026): fuera el panel «Distancia al objetivo» bajo el precio; el % va
// al lado de la etiqueta «Objetivo analistas» de la línea discontinua, en verde (potencial) o rojo.
// También se vigila que nada global pise el formato de cada serie (bug de #4472: «99,10 US$»).
type PriceLineOpts = { price: number; title: string; color: string; axisLabelColor?: string; axisLabelVisible?: boolean };
const captured = vi.hoisted(() => ({
    chart: null as null | Record<string, unknown>,
    series: [] as Array<{ kind: string; opts: Record<string, unknown>; pane?: number }>,
    priceLines: [] as PriceLineOpts[],
    data: {} as Record<string, unknown[]>,
    target: 241.5 as number | null,
}));
vi.mock('@/lib/actions/company-chart.actions', () => ({ getCompanyChartHistory: vi.fn() }));
vi.mock('@/lib/actions/price-events.actions', () => ({
    getChartEvents: vi.fn(async () => ({ events: [], averageCost: null, firstBuyDate: null, target: captured.target, targetCurrency: 'USD' })),
}));
vi.mock('lightweight-charts', () => {
    const stub = (): unknown => new Proxy({}, { get: (_t, key) => (key === 'then' ? undefined : vi.fn(() => stub())) });
    const seriesStub = (kind: string): unknown => new Proxy({}, { get: (_t, key) => {
        if (key === 'then') return undefined;
        if (key === 'setData') return (rows: unknown[]) => { captured.data[kind] = rows; };
        if (key === 'createPriceLine') return (opts: PriceLineOpts) => { captured.priceLines.push(opts); return stub(); };
        return vi.fn(() => stub());
    } });
    return {
        AreaSeries: 'Area', LineSeries: 'Line', CandlestickSeries: 'Candlestick', HistogramSeries: 'Histogram', LineStyle: { Dashed: 2 }, ColorType: { Solid: 'solid' },
        createSeriesMarkers: () => stub(),
        createChart: (_el: unknown, opts: Record<string, unknown>) => {
            captured.chart = opts;
            return new Proxy({}, { get: (_t, key) => {
                if (key === 'addSeries') return (kind: string, o: Record<string, unknown>, pane?: number) => { captured.series.push({ kind, opts: o, pane }); return seriesStub(kind); };
                if (key === 'panes') return () => [stub(), stub()];
                if (key === 'then') return undefined;
                return vi.fn(() => stub());
            } });
        },
    };
});

// Último cierre del tramo 1M: 161 (102 + 59).
const history = Array.from({ length: 60 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 7, 29 + i)).toISOString().slice(0, 10),
    open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i, volume: 1000 + i,
}));
const snapshot: CompanyMarketSnapshot = {
    ticker: 'AAPL', name: 'Fixture', exchange: 'NASDAQ', currency: 'USD',
    history, historyCurrency: 'USD', historySource: 'Fixture local', status: 'available',
    quote: { price: null, change: null, changePercent: null, open: null, high: null, low: null,
        previousClose: null, priceAsOf: null, priceKind: null },
};

type Fmt = { type: string; formatter?: (v: number) => string };
const nb = (text: string) => text.replace(/\u00a0|\u202f/g, ' ');
const targetLine = () => captured.priceLines.filter((line) => line.price === captured.target).at(-1);

describe('CompanyTechnicalChart: línea del objetivo con su % y sin panel del indicador', () => {
    beforeAll(() => {
        // jsdom no trae matchMedia (lo consulta el gráfico tras montarse).
        if (typeof window.matchMedia !== 'function') {
            window.matchMedia = ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as typeof window.matchMedia;
        }
    });
    beforeEach(() => { captured.series = []; captured.priceLines = []; captured.chart = null; captured.data = {}; });

    it('solo dos paneles (precio y volumen); ningún formato global pisa el de cada serie', async () => {
        captured.target = 241.5;
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        // Tres series desde el 5-nov-2026: Area (línea) + Candlestick (velas
        // cuando TODAS las barras traen OHLC) + volumen; solo una serie de
        // precio lleva datos en cada render.
        await waitFor(() => expect(captured.series.length).toBe(3));
        const localization = captured.chart?.localization as Record<string, unknown>;
        expect(localization.priceFormatter).toBeUndefined();
        const [price, , volume] = captured.series;
        expect(captured.series.map((s) => s.kind)).toEqual(['Area', 'Candlestick', 'Histogram']);
        expect(captured.series.some((s) => s.kind === 'Line')).toBe(false);
        expect(volume.pane).toBe(1);
        expect((volume.opts.priceFormat as Fmt).type).toBe('volume');
        const main = price.opts.priceFormat as Fmt;
        expect(main.type).toBe('custom');
        expect(nb(main.formatter!(40))).toMatch(/40,00\s?US\$/);
    });

    it('empieza en línea y permite alternar a velas y volver sin duplicar precios', async () => {
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(captured.data.Area?.length).toBeGreaterThan(0));
        const line = screen.getByRole('button', { name: /^Línea$/ });
        const candles = screen.getByRole('button', { name: /^Velas$/ });
        expect(line.getAttribute('aria-pressed')).toBe('true');
        expect(captured.data.Candlestick).toEqual([]);
        fireEvent.click(candles);
        await waitFor(() => expect(captured.data.Candlestick?.length).toBeGreaterThan(0));
        expect(captured.data.Area).toEqual([]);
        expect(candles.getAttribute('aria-pressed')).toBe('true');
        fireEvent.click(line);
        await waitFor(() => expect(captured.data.Area?.length).toBeGreaterThan(0));
        expect(captured.data.Candlestick).toEqual([]);
    });

    it('sin OHLC completo mantiene línea y no ofrece velas falsas', async () => {
        render(<CompanyTechnicalChart snapshot={{ ...snapshot, history: history.map((row) => ({ ...row, open: null })) }} />);
        const candles = screen.getByRole('button', { name: /^Velas$/ });
        expect(candles.hasAttribute('disabled')).toBe(true);
        await waitFor(() => expect(captured.data.Area?.length).toBeGreaterThan(0));
        expect(captured.data.Candlestick).toEqual([]);
    });

    it('con potencial: «Objetivo analistas · +50,00 %» en verde, línea violeta y precio en el eje', async () => {
        captured.target = 241.5;
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(targetLine()).toBeDefined());
        const line = targetLine()!;
        expect(nb(line.title)).toBe('Objetivo analistas · +50,00 %');
        expect(line.color).toBe('#a78bfa');
        expect(line.axisLabelColor).toBe('#22c55e');
        expect(line.axisLabelVisible).toBe(true);
    });

    it('con el precio por encima del objetivo: % negativo en rojo', async () => {
        captured.target = 120.75;
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(targetLine()).toBeDefined());
        const line = targetLine()!;
        expect(nb(line.title)).toBe('Objetivo analistas · -25,00 %');
        expect(line.axisLabelColor).toBe('#ef4444');
    });

    it('en inglés: «Analyst target · +50.00%»', async () => {
        captured.target = 241.5;
        render(<LocaleProvider locale="en"><CompanyTechnicalChart snapshot={snapshot} /></LocaleProvider>);
        await waitFor(() => expect(targetLine()).toBeDefined());
        expect(nb(targetLine()!.title)).toBe('Analyst target · +50.00%');
        expect(targetLine()!.axisLabelColor).toBe('#22c55e');
    });
});
