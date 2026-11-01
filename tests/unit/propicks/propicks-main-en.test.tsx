import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ProPick } from '@/lib/actions/proPicks.actions';

vi.mock('@/lib/actions/proPicks.actions', () => ({ generateEnhancedProPicksWithRun: vi.fn(), generateProPicksForStrategy: vi.fn() }));
vi.mock('@/lib/actions/propicks-funnel.actions', () => ({ generateFunnelRunNow: vi.fn() }));
vi.mock('@/lib/actions/propicks-backtest.actions', () => ({ runWalkForwardBacktest: vi.fn() }));
vi.mock('@/lib/actions/watchlist.actions', () => ({ addToWatchlist: vi.fn() }));
vi.mock('@/components/proPicks/TrackRecordView', () => ({ default: () => <div>track</div> }));
vi.mock('@/components/proPicks/DcaBacktestPanel', () => ({ default: () => <div>dca</div> }));

import EnhancedProPicksContent from '@/components/proPicks/EnhancedProPicksContent';
import EnhancedProPicksFilters from '@/components/proPicks/EnhancedProPicksFilters';
import ProPicksLoadError from '@/components/proPicks/ProPicksLoadError';
import ProPicksTabs from '@/components/proPicks/ProPicksTabs';
import { LocaleProvider } from '@/lib/i18n/client';

const filters = { timePeriod: 'month', limit: 20, minScore: 80, sector: 'Technology', sortBy: 'score' } as const;

const pick = {
    symbol: 'MSFT', company: 'Microsoft Corp', sector: 'Technology', score: 82.5, grade: 'A', isStrongBuy: false,
    currentPrice: 410, priceAsOf: '2026-10-30', priceCurrency: 'USD', upsidePotential: 12.3, confidence: 70, confidenceLevel: 'High',
    confidenceReasons: [], asOf: '2026-10-30', categoryScores: { value: 50, momentum: 50, profitability: 90, growth: 70, health: 70, cash: 70 },
} as unknown as ProPick;

describe('Pro Picks en inglés: pestañas, filtros, selección y error de carga', () => {
    it('el error de carga sale en inglés y en español sigue igual', () => {
        const { unmount } = render(<ProPicksLoadError locale="en" statusCode={429} />);
        expect(screen.getByRole('heading', { name: "ProPicks couldn't load" })).toBeTruthy();
        expect(screen.getByRole('alert').textContent).toBe('The request hit the rate limit. Try again in a few seconds.');
        expect(screen.getByRole('link', { name: /Retry/ })).toBeTruthy();
        unmount();
        render(<ProPicksLoadError statusCode={403} />);
        expect(screen.getByRole('heading', { name: 'ProPicks no se pudo cargar' })).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Iniciar sesión' })).toBeTruthy();
    });

    it('los filtros salen en inglés', () => {
        render(<LocaleProvider locale="en"><EnhancedProPicksFilters filters={filters} onFiltersChange={() => {}} onApply={() => {}} /></LocaleProvider>);
        expect(screen.getByText('Filters')).toBeTruthy();
        expect(screen.getByText('2 filters')).toBeTruthy();
        expect(screen.getByText('Number of stocks: 20')).toBeTruthy();
        expect(screen.getByText('Minimum score: 80')).toBeTruthy();
        expect(screen.getByText('Sort by')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Apply filters/ })).toBeTruthy();
        expect(screen.queryByText(/Filtros|Ordenar por|Aplicar/)).toBeNull();
    });

    it('la selección vacía y la tarjeta salen en inglés', () => {
        const { unmount } = render(<LocaleProvider locale="en"><EnhancedProPicksContent initialPicks={[]} initialPassedCount={null} /></LocaleProvider>);
        expect(screen.getByText('No selection')).toBeTruthy();
        expect(screen.getByText(/hasn't published a completed run yet/)).toBeTruthy();
        expect(screen.getAllByRole('button', { name: /Generate selection now|Refresh selection/ }).length).toBeGreaterThan(0);
        unmount();
        render(<LocaleProvider locale="en"><EnhancedProPicksContent initialPicks={[pick]} generatedAt="2026-10-30T10:00:00Z" initialPassedCount={1} /></LocaleProvider>);
        expect(screen.getByText('Top 1')).toBeTruthy();
        expect(screen.getByText('Score')).toBeTruthy();
        expect(screen.getByText('Upside (12m)')).toBeTruthy();
        expect(screen.getByText('View full analysis')).toBeTruthy();
        expect(screen.getByText(/sorted by overall score/)).toBeTruthy();
        expect(screen.queryByText(/Ver análisis|Puntuación|Potencial/)).toBeNull();
    });

    it('las pestañas y el backtest salen en inglés', () => {
        render(<LocaleProvider locale="en"><ProPicksTabs strategies={[]} initialPicks={[]} /></LocaleProvider>);
        expect(screen.getByRole('tablist', { name: 'Pro Picks sections' })).toBeTruthy();
        for (const name of ['AI selection', 'Gems', 'Deep value', 'Strategy & rebalancing', 'Backtest', 'AI simulated results', 'Global radar', 'DCA opportunities']) {
            expect(screen.getByRole('tab', { name })).toBeTruthy();
        }
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Backtest' }));
    });
});
