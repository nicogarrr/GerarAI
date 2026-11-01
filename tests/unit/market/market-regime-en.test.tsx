import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('@/lib/actions/market-regime.actions', () => ({
    getMarketRegimeResult: async () => ({
        error: null,
        data: {
            status: 'disponible',
            date: '2026-10-30',
            generated_at: null,
            note: null,
            probabilities: { state_0: 0.7, state_1: 0.3 },
            metrics: {
                treasury_10y_us: { value: 4.25, unit: 'porcentaje', date: '2026-10-30' },
                hmm: { status: 'disponible', date: '2026-10-30', trained_through: '2026-10-29', training_sessions: 1 },
                top_ten_sp500: { status: 'sin_datos', reason: 'no_snapshot_in_disk' },
            },
            portfolio_beta: { status: 'no_disponible' },
        },
    }),
}));

import { MarketRegimeVista, trainingSessionsText } from '@/components/market/MarketRegime';
import { MoversTable } from '@/components/market/MoversTable';

const sets = { portfolioTickers: new Set<string>(), watchlistTickers: new Set<string>() };

describe('Régimen de mercado y tabla de movimientos en inglés', () => {
    it('régimen en inglés', async () => {
        mocks.locale = 'en';
        render(await MarketRegimeVista());
        expect(screen.getByText('Available')).toBeTruthy();
        expect(screen.getByText('US 10-year Treasury')).toBeTruthy();
        expect(screen.getByText('4.25%')).toBeTruthy();
        expect(screen.getByText('State model (HMM)')).toBeTruthy();
        expect(screen.getByText('State 0')).toBeTruthy();
        expect(screen.getByText('The S&P 500 factsheet is not loaded yet; it will appear at the next sync.')).toBeTruthy();
        expect(screen.getByText('Unavailable')).toBeTruthy();
    });

    it('en español no cambia', async () => {
        mocks.locale = 'es';
        render(await MarketRegimeVista());
        expect(screen.getByText('Bono EE. UU. 10 años')).toBeTruthy();
        expect(screen.getByText('4,25 %')).toBeTruthy();
        expect(screen.getByText('Estado 0')).toBeTruthy();
        expect(trainingSessionsText(1)).toBe('1 sesión');
        expect(trainingSessionsText(2, 'en')).toBe('2 sessions');
    });

    it('tabla vacía y cabeceras según idioma', async () => {
        mocks.locale = 'en';
        render(await MoversTable({ rows: [], caption: 'Top gainers', tickerSets: sets }));
        expect(screen.getByText('No data yet — it will show here as soon as prices are recorded.')).toBeTruthy();
        mocks.locale = 'es';
        render(await MoversTable({ rows: [], caption: 'Mayores subidas', tickerSets: sets }));
        expect(screen.getByText('Sin datos todavía — en cuanto haya precios registrados aparecerán aquí.')).toBeTruthy();
    });
});
