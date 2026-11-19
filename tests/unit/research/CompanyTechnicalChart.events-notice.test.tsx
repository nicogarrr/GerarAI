import { render, screen, waitFor } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { LocaleProvider } from '@/lib/i18n/client';

// Aviso de recorte del timeline (#6009): el tramo puede no mostrar todos los
// eventos. Distinto del holdingNotice (calidad del coste medio): otro texto,
// otro testid, otro color — no pueden confundirse ni pisarse.
const captured = vi.hoisted(() => ({
    events: { events: [], averageCost: null as number | null, firstBuyDate: '2025-08-29' as string | null, holdingNotice: null as string | null, eventsNotice: null as string | null, target: null as number | null, targetCurrency: 'USD' as string | null },
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

const NOTICE_ES = 'Se muestran solo los eventos más recientes del rango. Hay eventos omitidos; el primer día mostrado puede estar incompleto. Reduce el rango de fechas para consultar el resto.';
const NOTICE_EN = 'Only the most recent events in the range are shown. Some events were omitted; the first day shown may be incomplete. Narrow the date range to see the rest.';
const HOLDING_ES = 'Coste medio no comparable: faltan cantidades/costes válidos o las divisas no coinciden. No se ha inferido un tipo de cambio.';

describe('CompanyTechnicalChart: aviso de recorte del timeline', () => {
    beforeAll(() => {
        if (typeof window.matchMedia !== 'function') {
            window.matchMedia = ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })) as typeof window.matchMedia;
        }
    });
    beforeEach(() => {
        captured.events = { events: [], averageCost: null, firstBuyDate: '2025-08-29', holdingNotice: null, eventsNotice: null, target: null, targetCurrency: 'USD' };
    });

    it('enseña el aviso de recorte junto al gráfico', async () => {
        captured.events.eventsNotice = NOTICE_ES;
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(screen.getByTestId('chart-events-notice')).toHaveTextContent(NOTICE_ES));
    });

    it('en inglés se sirve el texto en inglés', async () => {
        captured.events.eventsNotice = NOTICE_EN;
        render(<LocaleProvider locale="en"><CompanyTechnicalChart snapshot={snapshot} /></LocaleProvider>);
        await waitFor(() => expect(screen.getByTestId('chart-events-notice')).toHaveTextContent(NOTICE_EN));
    });

    it('convive con el holdingNotice sin pisarse: cada aviso con su texto y su testid', async () => {
        captured.events.eventsNotice = NOTICE_ES;
        captured.events.holdingNotice = HOLDING_ES;
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(screen.getByTestId('chart-events-notice')).toHaveTextContent(NOTICE_ES));
        expect(screen.getByTestId('chart-holding-notice')).toHaveTextContent(HOLDING_ES);
        expect(screen.getByTestId('chart-events-notice')).not.toHaveTextContent(HOLDING_ES);
        expect(screen.getByTestId('chart-holding-notice')).not.toHaveTextContent(NOTICE_ES);
    });

    it('sin recorte no hay aviso de eventos', async () => {
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        await waitFor(() => expect(screen.getByRole('button', { name: '1M' })).toBeInTheDocument());
        expect(screen.queryByTestId('chart-events-notice')).toBeNull();
    });
});
