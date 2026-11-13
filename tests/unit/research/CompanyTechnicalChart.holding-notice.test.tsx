import { render, screen, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { LocaleProvider } from '@/lib/i18n/client';

// El gráfico solo enseña el aviso de calidad del coste medio cuando hay posición pero el
// coste no es comparable (sin línea «Tu precio medio»); con coste comparable no sale nada.
const captured = vi.hoisted(() => ({
    events: { events: [], averageCost: null as number | null, firstBuyDate: '2025-08-29' as string | null, holdingNotice: null as string | null, target: null as number | null, targetCurrency: 'USD' as string | null },
}));
vi.mock('@/lib/actions/company-chart.actions', () => ({ getCompanyChartHistory: vi.fn() }));
vi.mock('@/lib/actions/price-events.actions', () => ({ getChartEvents: vi.fn(async () => captured.events) }));
vi.mock('lightweight-charts', () => {
    const stub = (): unknown => new Proxy({}, { get: (_t, key) => (key === 'then' ? undefined : vi.fn(() => stub())) });
    return {
        AreaSeries: 'Area', LineSeries: 'Line', CandlestickSeries: 'Candlestick', HistogramSeries: 'Histogram', LineStyle: { Dashed: 2 }, ColorType: { Solid: 'solid' },
        createSeriesMarkers: () => stub(),
        createChart: () => new Proxy({}, { get: (_t, key) => (key === 'then' ? undefined : vi.fn(() => stub())) }),
    };
});

const history = Array.from({ length: 40 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 7, 29 + i)).toISOString().slice(0, 10),
    open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i, volume: 1000 + i,
}));
const snapshot: CompanyMarketSnapshot = {
    ticker: 'AAPL', name: 'Fixture', exchange: 'NASDAQ', currency: 'USD',
    history, historyCurrency: 'USD', historySource: 'Fixture local', status: 'available',
    quote: { price: null, change: null, changePercent: null, open: null, high: null, low: null,
        previousClose: null, priceAsOf: null, priceKind: null },
};

const NOTICE_ES = 'Coste medio no comparable: faltan cantidades/costes válidos o las divisas no coinciden. No se ha inferido un tipo de cambio.';
const NOTICE_EN = 'Average cost not comparable: missing valid quantities/costs or the currencies do not match. No exchange rate was inferred.';

describe('CompanyTechnicalChart: aviso de calidad del coste medio', () => {
    beforeAll(() => {
        if (typeof window.matchMedia !== 'function') {
            window.matchMedia = ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as typeof window.matchMedia;
        }
    });
    beforeEach(() => {
        captured.events = { events: [], averageCost: null, firstBuyDate: '2025-08-29', holdingNotice: null, target: null, targetCurrency: 'USD' };
    });

    it('enseña el aviso cuando hay posición y el coste medio no es comparable', async () => {
        captured.events.holdingNotice = NOTICE_ES;
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(screen.getByTestId('chart-holding-notice')).toHaveTextContent(NOTICE_ES));
    });

    it('el aviso llega traducido desde la acción (en inglés se sirve el texto en inglés)', async () => {
        captured.events.holdingNotice = NOTICE_EN;
        render(<LocaleProvider locale="en"><CompanyTechnicalChart snapshot={snapshot} /></LocaleProvider>);
        await waitFor(() => expect(screen.getByTestId('chart-holding-notice')).toHaveTextContent(NOTICE_EN));
    });

    it('con coste comparable no hay aviso y la línea de precio medio sigue saliendo', async () => {
        captured.events = { ...captured.events, averageCost: 151.25, holdingNotice: null };
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(screen.getByRole('button', { name: /Desde compra/ })).toBeInTheDocument());
        expect(screen.queryByTestId('chart-holding-notice')).toBeNull();
    });

    it('sin posición no hay aviso ni botón «Desde compra»', async () => {
        captured.events = { events: [], averageCost: null, firstBuyDate: null, holdingNotice: null, target: null, targetCurrency: 'USD' };
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(screen.getByRole('button', { name: '1M' })).toBeInTheDocument());
        expect(screen.queryByTestId('chart-holding-notice')).toBeNull();
        expect(screen.queryByRole('button', { name: /Desde compra/ })).toBeNull();
    });
});
