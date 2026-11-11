import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// El inicio pide sus TRES secciones rápidas en PARALELO a route handlers
// propios (app/api/home/*): las server actions de un cliente se ejecutan en
// serie y el POST agrupado anterior devolvía las tres secciones a la vez, así
// la más rápida esperaba a la más lenta (cartera 64 ms, respuesta 344 ms por
// la watchlist; medido en prod, 11-nov-2026). Oportunidades va en su propia
// llamada: su sondeo DCF cotiza con proveedores externos en síncrono (~7 s
// medidos en prod, 31-oct).

vi.mock('@/components/HomeAttention', () => ({ default: () => <div>Atención aislada</div> }));

const getPortfolioSummary = vi.fn();
const getUserAlerts = vi.fn();
const getRecentTriggeredAlerts = vi.fn();
const getHomeWatchlistPreview = vi.fn();
const getHomeOpportunities = vi.fn();
const getHoldingSignals = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioSummary: (...a: unknown[]) => getPortfolioSummary(...a) }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    getUserAlerts: () => getUserAlerts(),
    getRecentTriggeredAlerts: (...a: unknown[]) => getRecentTriggeredAlerts(...a),
}));
vi.mock('@/lib/actions/home-overview.actions', () => ({
    getHomeWatchlistPreview: (...a: unknown[]) => getHomeWatchlistPreview(...a),
    getHomeOpportunities: (...a: unknown[]) => getHomeOpportunities(...a),
}));
vi.mock('@/lib/actions/holding-signals.actions', () => ({ getHoldingSignals: (...a: unknown[]) => getHoldingSignals(...a) }));
vi.mock('@/components/portfolio/PortfolioValueBreakdown', () => ({
    PortfolioValueBreakdown: ({ summary }: { summary: { totalValue: number } }) => <div>desglose {summary.totalValue}</div>,
}));
vi.mock('@/components/research/ExternalNewsHeadline', () => ({
    ExternalNewsHeadline: ({ headline }: { headline: string }) => <span>{headline}</span>,
}));

import PersonalizedOverview from '@/components/PersonalizedOverview';

const holding = {
    symbol: 'AAPL', quantity: 1, avgPrice: 10, currentPrice: 12, valuationHold: null, value: 1200, cost: 1000, gain: 200,
    gainPercent: 20, nativeCurrency: 'USD', baseCurrency: 'EUR', fxMissing: false, nativeGain: null, nativeCost: null,
    valueMissing: false, firstBuyDate: null, holdingDays: null, fiscalBucket: null,
};

const summary = {
    totalValue: 5000, totalCost: 4000, totalGain: 1000, totalGainPercent: 25, holdings: [holding], equityValue: 4000, cash: 1000,
};

type Resolver = (response: Response) => void;

describe('PersonalizedOverview primera carga', () => {
    const fetchMock = vi.fn();
    const pending = new Map<string, Resolver[]>();

    const respond = (urlPart: string, body: unknown) => {
        const resolvers = pending.get(urlPart) ?? [];
        for (const resolve of resolvers) resolve(Response.json(body));
        pending.delete(urlPart);
    };

    beforeEach(() => {
        vi.clearAllMocks();
        pending.clear();
        // Cada sección cuelga hasta que el test la resuelve: así se fija
        // qué se pide y que ninguna sección espera a otra.
        fetchMock.mockImplementation((url: RequestInfo | URL) => new Promise<Response>((resolve) => {
            const key = String(url);
            pending.set(key, [...(pending.get(key) ?? []), resolve]);
        }));
        vi.stubGlobal('fetch', fetchMock);
        getHoldingSignals.mockResolvedValue({ fairValues: {}, dca: null });
        getHomeOpportunities.mockRejectedValue(new Error('sin red'));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('tres fetch en paralelo (uno por sección), ninguna server action suelta', async () => {
        render(<PersonalizedOverview userId="u1" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        const urls = fetchMock.mock.calls.map((call) => String(call[0]));
        expect(urls).toContain('/api/home/portfolio');
        expect(urls).toContain('/api/home/alerts');
        expect(urls).toContain('/api/home/watchlist?limit=3');
        for (const read of [getPortfolioSummary, getUserAlerts, getRecentTriggeredAlerts, getHomeWatchlistPreview]) {
            expect(read).not.toHaveBeenCalled();
        }
    });

    it('cada sección pinta en cuanto llega: cartera no espera a la watchlist', async () => {
        render(<PersonalizedOverview userId="u1" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        // La watchlist sigue colgada: cartera y alertas responden ya.
        respond('/api/home/portfolio', { data: summary, error: null });
        respond('/api/home/alerts', { data: { rules: [], triggered: [] }, error: null });
        expect(await screen.findByText('desglose 5000')).toBeInTheDocument();
        // La sección de watchlist sigue cargando (skeleton presente): no
        // hubo que esperarla para pintar cartera.
        expect(screen.queryAllByText(/Cargando(?:…|\.\.\.)/u).length).toBeGreaterThan(0);
        // Al llegar la watchlist, su sección termina sin tocar a las demás.
        respond('/api/home/watchlist?limit=3', { data: { unavailable: false, total: 0, items: [] }, error: null });
        await waitFor(() => expect(screen.queryAllByText(/Cargando(?:…|\.\.\.)/u)).toHaveLength(0));
    });

    it('el error de una sección se queda en su sección', async () => {
        render(<PersonalizedOverview userId="u1" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        respond('/api/home/portfolio', { data: summary, error: null });
        respond('/api/home/alerts', { data: { rules: [], triggered: [] }, error: 'ui.sectionError.generic' });
        respond('/api/home/watchlist?limit=3', { data: { unavailable: false, total: 0, items: [] }, error: null });
        expect(await screen.findByText('desglose 5000')).toBeInTheDocument();
        // Oportunidades (rechazada) + alertas: dos secciones con aviso, la
        // cartera intacta.
        await waitFor(() => expect(screen.queryAllByText(/No se pudieron cargar los datos/).length).toBeGreaterThanOrEqual(2));
    });

    it('oportunidades se piden APARTE tras el primer pintado, nunca en las secciones rápidas', async () => {
        render(<PersonalizedOverview userId="u1" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
        // Regression: en su día las oportunidades viajaban DENTRO del primer
        // POST (sondeo DCF ~7 s medidos en prod) y retenían el pintado de
        // cartera, alertas y watchlist.
        expect(getHomeOpportunities).toHaveBeenCalledTimes(1);
        expect(getHomeOpportunities).toHaveBeenCalledWith(
            expect.objectContaining({ marketCapMoreThan: expect.any(Number), limit: 10, candidateLimit: expect.any(Number) }),
        );
        for (const call of fetchMock.mock.calls) {
            expect(String(call[0])).not.toContain('opportunities');
        }
    });
});
