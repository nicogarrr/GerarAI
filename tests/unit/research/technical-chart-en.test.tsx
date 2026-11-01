import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';
import { movementEvents } from '@/lib/market/price-events';

vi.mock('@/lib/actions/company-chart.actions', () => ({ getCompanyChartHistory: vi.fn() }));
vi.mock('@/lib/actions/price-events.actions', () => ({ getChartEvents: vi.fn(() => new Promise(() => undefined)) }));
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

describe('gráfico técnico en inglés', () => {
    it('lectura técnica, rangos y estructura en inglés', () => {
        render(<LocaleProvider locale="en"><CompanyTechnicalChart snapshot={snapshot} /></LocaleProvider>);
        const reading = screen.getByTestId('technical-reading');
        expect(reading).toHaveTextContent('Bullish');
        expect(reading).toHaveTextContent('Higher highs and higher lows');
        expect(reading).toHaveTextContent('above the 50-session average');
        expect(reading).not.toHaveTextContent('Alcista');
        expect(screen.getByRole('button', { name: '1Y' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Max' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Máx' })).toBeNull();
    });

    it('en español se mantiene igual', () => {
        render(<CompanyTechnicalChart snapshot={snapshot} />);
        const reading = screen.getByTestId('technical-reading');
        expect(reading).toHaveTextContent('Alcista');
        expect(reading).toHaveTextContent('Máximos y mínimos crecientes entre los dos últimos bloques de 10 sesiones.');
        expect(screen.getByRole('button', { name: 'Máx' })).toBeInTheDocument();
    });

    it('«¿Por qué se movió?» en inglés con número en formato inglés', () => {
        const move = { date: '2026-03-02', change: 0.06, byPrice: true, byVolume: true, volumeRatio: 3.25 } as never;
        const [event] = movementEvents([move], [], createTranslator('en'), 'en');
        expect(event.title).toBe('Why did it move? +6.0% on the day, volume 3.3× the 60-session average');
        expect(event.detail).toMatch(/^No saved news/);
        expect(event.source).toBe('GerarAI calculation from daily prices');
    });
});
