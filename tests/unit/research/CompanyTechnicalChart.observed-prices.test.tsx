import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';

vi.mock('@/lib/actions/company-chart.actions', () => ({ getCompanyChartHistory: vi.fn() }));
// Canvas geometry is covered in the browser, not in jsdom.
vi.mock('lightweight-charts', () => ({ createChart: () => { throw new Error('no canvas in jsdom'); } }));

const history = Array.from({ length: 60 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 7, 29 + i)).toISOString().slice(0, 10),
    open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i, volume: null,
}));
const snapshot: CompanyMarketSnapshot = {
    ticker: 'AAPL', name: 'Fixture', exchange: 'NASDAQ', currency: 'USD',
    history, historyCurrency: 'USD', historySource: 'Fixture local', status: 'available',
    quote: { price: null, change: null, changePercent: null, open: null, high: null, low: null,
        previousClose: null, priceAsOf: null, priceKind: null },
};

describe('daily price finality is not provided by the candle contract', () => {
    it.each(['2026-10-27T17:45:00Z', '2026-10-28T08:00:00Z'])(
        'does not invent a confirmed close based on the clock (%s)', (now) => {
            vi.spyOn(Date, 'now').mockReturnValue(Date.parse(now));
            render(<CompanyTechnicalChart snapshot={snapshot} />);
            const reading = screen.getByTestId('technical-reading');
            expect(reading).toHaveTextContent('Precios diarios observados hasta');
            expect(reading).toHaveTextContent('Último precio diario');
            expect(reading).toHaveTextContent('no confirma el cierre de la última vela');
            expect(reading).toHaveTextContent('La lectura técnica y los niveles son provisionales');
            expect(reading).not.toHaveTextContent('Pivotes de referencia de la última vela');
            expect(reading).not.toHaveTextContent('Cierres diarios hasta');
            expect(reading).not.toHaveTextContent('Niveles clave del día');
            expect(reading).toHaveTextContent('Niveles de retroceso');
        },
    );
    it('does not claim an observed last price or provisional bar when there are no bars', () => {
        render(<CompanyTechnicalChart snapshot={{ ...snapshot, history: [] }} />);
        expect(screen.getByTestId('technical-reading')).not.toHaveTextContent('Precios diarios observados hasta');
        expect(screen.getByTestId('technical-reading')).not.toHaveTextContent('Último precio diario');
    });
});
