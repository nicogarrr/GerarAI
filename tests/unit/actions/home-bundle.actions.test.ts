import { beforeEach, describe, expect, it, vi } from 'vitest';

const getPortfolioSummary = vi.fn();
const getUserAlerts = vi.fn();
const getRecentTriggeredAlerts = vi.fn();
const getHomeWatchlistPreview = vi.fn();
const getHomeOpportunities = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioSummary: (...a: unknown[]) => getPortfolioSummary(...a) }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    getUserAlerts: () => getUserAlerts(),
    getRecentTriggeredAlerts: (...a: unknown[]) => getRecentTriggeredAlerts(...a),
}));
vi.mock('@/lib/actions/home-overview.actions', () => ({
    getHomeWatchlistPreview: (...a: unknown[]) => getHomeWatchlistPreview(...a),
    getHomeOpportunities: (...a: unknown[]) => getHomeOpportunities(...a),
}));

import { getHomeOverviewBundle } from '@/lib/actions/home-bundle.actions';

const params = { watchlistLimit: 3, marketCapMoreThan: 10, limit: 10, candidateLimit: 5 };

describe('getHomeOverviewBundle', () => {
    beforeEach(() => vi.clearAllMocks());

    it('lanza las cuatro lecturas a la vez, no en cadena', async () => {
        const gates: Array<() => void> = [];
        const pending = <T,>(value: T) => new Promise<T>((resolve) => gates.push(() => resolve(value)));
        getPortfolioSummary.mockImplementation(() => pending({ totalValue: 1 }));
        getUserAlerts.mockImplementation(() => pending([]));
        getRecentTriggeredAlerts.mockImplementation(() => pending([]));
        getHomeWatchlistPreview.mockImplementation(() => pending({ unavailable: false, total: 0, items: [] }));
        getHomeOpportunities.mockImplementation(() => pending([]));

        const bundle = getHomeOverviewBundle('u1', params);
        await Promise.resolve();
        // Todas en vuelo antes de que ninguna termine.
        expect(gates).toHaveLength(5);
        gates.forEach((open) => open());
        const result = await bundle;
        expect(result.portfolio).toEqual({ data: { totalValue: 1 }, error: null });
        expect(getHomeWatchlistPreview).toHaveBeenCalledWith(3);
        expect(getHomeOpportunities).toHaveBeenCalledWith({ marketCapMoreThan: 10, limit: 10, candidateLimit: 5 });
    });

    it('un fallo se queda en su sección y solo viaja el mensaje genérico', async () => {
        getPortfolioSummary.mockRejectedValue(new Error('ECONNREFUSED 10.0.0.3:8000 /internal/path'));
        getUserAlerts.mockResolvedValue([]);
        getRecentTriggeredAlerts.mockResolvedValue([]);
        getHomeWatchlistPreview.mockResolvedValue({ unavailable: true, total: 0, items: [] });
        getHomeOpportunities.mockResolvedValue([]);

        const result = await getHomeOverviewBundle('u1', params);
        expect(result.portfolio.data).toBeNull();
        // La acción viaja solo la clave genérica por categoría (sin rutas ni
        // detalles internos); el texto lo resuelve el cliente con t().
        expect(result.portfolio.error).toBe('ui.sectionError.network');
        expect(result.watchlist.error).not.toBeNull();
        expect(result.alerts).toEqual({ data: { rules: [], triggered: [] }, error: null });
        expect(result.opportunities).toEqual({ data: [], error: null });
    });
});
