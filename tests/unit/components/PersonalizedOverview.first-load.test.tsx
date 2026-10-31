import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// El inicio pide sus cuatro secciones en UNA server action (Next ejecuta en
// serie las server actions de un cliente: antes eran cuatro POST encadenados).

vi.mock('@/components/HomeAttention', () => ({ default: () => <div>Atención aislada</div> }));

const getPortfolioSummary = vi.fn();
const getUserAlerts = vi.fn();
const getRecentTriggeredAlerts = vi.fn();
const getHomeWatchlistPreview = vi.fn();
const getHomeOpportunities = vi.fn();
const getHoldingSignals = vi.fn();
const getHomeOverviewBundle = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioSummary: (...a: unknown[]) => getPortfolioSummary(...a) }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    getUserAlerts: () => getUserAlerts(),
    getRecentTriggeredAlerts: (...a: unknown[]) => getRecentTriggeredAlerts(...a),
}));
vi.mock('@/lib/actions/home-overview.actions', () => ({
    getHomeWatchlistPreview: (...a: unknown[]) => getHomeWatchlistPreview(...a),
    getHomeOpportunities: (...a: unknown[]) => getHomeOpportunities(...a),
}));
vi.mock('@/lib/actions/home-bundle.actions', () => ({ getHomeOverviewBundle: (...a: unknown[]) => getHomeOverviewBundle(...a) }));
vi.mock('@/lib/actions/holding-signals.actions', () => ({ getHoldingSignals: (...a: unknown[]) => getHoldingSignals(...a) }));
vi.mock('@/components/portfolio/PortfolioValueBreakdown', () => ({
    PortfolioValueBreakdown: ({ summary }: { summary: { totalValue: number } }) => <div>desglose {summary.totalValue}</div>,
}));
vi.mock('@/components/research/ExternalNewsHeadline', () => ({
    ExternalNewsHeadline: ({ headline }: { headline: string }) => <span>{headline}</span>,
}));

import PersonalizedOverview from '@/components/PersonalizedOverview';

const summary = {
    totalValue: 5000, totalCost: 4000, totalGain: 1000, totalGainPercent: 25, holdings: [], equityValue: 4000, cash: 1000,
};

describe('PersonalizedOverview primera carga', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        getHoldingSignals.mockResolvedValue({ fairValues: {}, dca: null });
        getHomeOverviewBundle.mockResolvedValue({
            portfolio: { data: summary, error: null },
            alerts: { data: { rules: [], triggered: [] }, error: null },
            watchlist: { data: { unavailable: false, total: 0, items: [] }, error: null },
            opportunities: { data: [], error: 'No se pudieron cargar los datos. Reintenta en unos segundos.' },
        });
    });

    it('una sola server action para las cuatro secciones, ninguna lectura suelta', async () => {
        render(<PersonalizedOverview userId="u1" />);
        await waitFor(() => expect(screen.queryAllByText(/Cargando(?:…|\.\.\.)/u)).toHaveLength(0));
        expect(getHomeOverviewBundle).toHaveBeenCalledTimes(1);
        expect(getHomeOverviewBundle).toHaveBeenCalledWith('u1', expect.objectContaining({ watchlistLimit: 3 }));
        for (const read of [getPortfolioSummary, getUserAlerts, getRecentTriggeredAlerts, getHomeWatchlistPreview, getHomeOpportunities]) {
            expect(read).not.toHaveBeenCalled();
        }
        // El error de una sección se queda en su sección.
        expect((await screen.findAllByText(/No se pudieron cargar los datos/)).length).toBeGreaterThan(0);
    });
});
