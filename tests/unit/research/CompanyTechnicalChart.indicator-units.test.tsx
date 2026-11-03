import { render, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';

// Bug visto en prod (3-nov-2026): el panel «Distancia al objetivo» (en %) salía con eje y
// etiqueta en «US$». Causa: `localization.priceFormatter` de lightweight-charts pisa el
// priceFormat de todas las series. Aquí se capturan las opciones con las que se crea el gráfico.
const captured = vi.hoisted(() => ({ chart: null as null | Record<string, unknown>, series: [] as Array<{ kind: string; opts: Record<string, unknown>; pane?: number }> }));
vi.mock('@/lib/actions/company-chart.actions', () => ({ getCompanyChartHistory: vi.fn() }));
vi.mock('lightweight-charts', () => {
    const stub = (): unknown => new Proxy({}, { get: (_t, key) => (key === 'then' ? undefined : vi.fn(() => stub())) });
    return {
        AreaSeries: 'Area', LineSeries: 'Line', HistogramSeries: 'Histogram', LineStyle: { Dashed: 2 }, ColorType: { Solid: 'solid' },
        createSeriesMarkers: () => stub(),
        createChart: (_el: unknown, opts: Record<string, unknown>) => {
            captured.chart = opts;
            return new Proxy({}, { get: (_t, key) => {
                if (key === 'addSeries') return (kind: string, o: Record<string, unknown>, pane?: number) => { captured.series.push({ kind, opts: o, pane }); return stub(); };
                if (key === 'panes') return () => [stub(), stub(), stub()];
                if (key === 'then') return undefined;
                return vi.fn(() => stub());
            } });
        },
    };
});

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

describe('CompanyTechnicalChart: unidades de cada panel', () => {
    beforeAll(() => {
        // jsdom no trae matchMedia (lo consulta el gráfico tras montarse).
        if (typeof window.matchMedia !== 'function') {
            window.matchMedia = ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as typeof window.matchMedia;
        }
    });
    it('el panel del indicador muestra % con signo y el precio la moneda; nada global pisa los formatos', async () => {
        captured.series = [];
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(captured.series.length).toBe(3));
        const localization = captured.chart?.localization as Record<string, unknown>;
        expect(localization.priceFormatter).toBeUndefined();
        const [price, indicator, volume] = captured.series;
        expect(indicator.pane).toBe(1);
        const ind = indicator.opts.priceFormat as Fmt;
        expect(nb(ind.formatter!(99.1))).toBe('+99,10 %');
        expect(nb(ind.formatter!(-12.345))).toBe('-12,35 %');
        expect(ind.formatter!(99.1)).not.toMatch(/US\$|\$/);
        const main = price.opts.priceFormat as Fmt;
        expect(main.type).toBe('custom');
        expect(nb(main.formatter!(40))).toMatch(/40,00\s?US\$/);
        expect((volume.opts.priceFormat as Fmt).type).toBe('volume');
    });
});
