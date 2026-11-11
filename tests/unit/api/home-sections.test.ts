import { beforeEach, describe, expect, it, vi } from 'vitest';

// Route handlers de las secciones del inicio (app/api/home/*): cada sección
// responde en cuanto su lectura termina y un fallo se queda en su sección
// con la clave genérica por categoría (nunca el error crudo).

const h = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    getPortfolioSummary: vi.fn(),
    getUserAlerts: vi.fn(),
    getRecentTriggeredAlerts: vi.fn(),
    getHomeWatchlistPreview: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: h.requireAuthenticatedUser }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioSummary: h.getPortfolioSummary }));
vi.mock('@/lib/actions/alerts.actions', () => ({ getUserAlerts: h.getUserAlerts, getRecentTriggeredAlerts: h.getRecentTriggeredAlerts }));
vi.mock('@/lib/actions/home-overview.actions', () => ({ getHomeWatchlistPreview: h.getHomeWatchlistPreview }));

import { GET as portfolioGET } from '@/app/api/home/portfolio/route';
import { GET as alertsGET } from '@/app/api/home/alerts/route';
import { GET as watchlistGET } from '@/app/api/home/watchlist/route';
import { NextRequest } from 'next/server';
import { AuthenticationError } from '@/lib/types/errors';

const req = (url: string) => new NextRequest(`http://localhost${url}`);

beforeEach(() => {
    vi.resetAllMocks();
    h.requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
});

describe('GET /api/home/portfolio', () => {
    it('devuelve {data, error:null} con el resumen del usuario autenticado', async () => {
        const summary = { totalValue: 5000, holdings: [] };
        h.getPortfolioSummary.mockResolvedValue(summary);
        const res = await portfolioGET();
        expect(res.status).toBe(200);
        expect(res.headers.get('Cache-Control')).toBe('no-store');
        expect(await res.json()).toEqual({ data: summary, error: null });
        expect(h.getPortfolioSummary).toHaveBeenCalledWith('u1');
    });

    it('lectura caída: fallback null con clave genérica, nunca el error crudo', async () => {
        h.getPortfolioSummary.mockRejectedValue(new Error('ECONNREFUSED postgres://interno:5432'));
        const res = await portfolioGET();
        const body = await res.json();
        expect(body.data).toBeNull();
        expect(body.error).toBe('ui.sectionError.network');
        expect(JSON.stringify(body)).not.toContain('postgres');
    });
});

describe('GET /api/home/alerts', () => {
    it('reglas + últimas 3 disparadas en una respuesta', async () => {
        h.getUserAlerts.mockResolvedValue([{ _id: 'r1' }]);
        h.getRecentTriggeredAlerts.mockResolvedValue([{ id: 9 }]);
        const res = await alertsGET();
        expect(await res.json()).toEqual({ data: { rules: [{ _id: 'r1' }], triggered: [{ id: 9 }] }, error: null });
        expect(h.getRecentTriggeredAlerts).toHaveBeenCalledWith(3);
    });

    it('un fallo deja listas vacías con clave de error', async () => {
        h.getUserAlerts.mockRejectedValue(new Error('500 del backend'));
        const body = await (await alertsGET()).json();
        expect(body).toEqual({ data: { rules: [], triggered: [] }, error: 'ui.sectionError.server' });
    });
});

describe('GET /api/home/watchlist', () => {
    it('pasa el limit validado y devuelve la vista previa', async () => {
        h.getHomeWatchlistPreview.mockResolvedValue({ unavailable: false, total: 7, items: [{ symbol: 'AAPL' }] });
        const res = await watchlistGET(req('/api/home/watchlist?limit=5'));
        expect(await res.json()).toEqual({ data: { unavailable: false, total: 7, items: [{ symbol: 'AAPL' }] }, error: null });
        expect(h.getHomeWatchlistPreview).toHaveBeenCalledWith(5);
    });

    it('limit fuera de rango o inválido cae al tope por defecto', async () => {
        h.getHomeWatchlistPreview.mockResolvedValue({ unavailable: false, total: 0, items: [] });
        for (const url of ['/api/home/watchlist', '/api/home/watchlist?limit=abc', '/api/home/watchlist?limit=999', '/api/home/watchlist?limit=-2']) {
            await watchlistGET(req(url));
        }
        expect(h.getHomeWatchlistPreview.mock.calls.map((c) => c[0])).toEqual([3, 3, 3, 3]);
    });

    it('watchlist no disponible: error genérico con la tarjeta vacía, no un 500', async () => {
        h.getHomeWatchlistPreview.mockResolvedValue({ unavailable: true, total: 0, items: [] });
        const res = await watchlistGET(req('/api/home/watchlist?limit=3'));
        const body = await res.json();
        expect(res.status).toBe(200);
        expect(body.error).toBe('ui.sectionError.generic');
        expect(body.data).toEqual({ unavailable: false, total: 0, items: [] });
    });
});

describe('autenticación', () => {
    it('sin sesión: 401 JSON vía withAuthErrors en las tres secciones', async () => {
        h.requireAuthenticatedUser.mockRejectedValue(new AuthenticationError('sin sesión'));
        for (const call of [() => portfolioGET(), () => alertsGET(), () => watchlistGET(req('/api/home/watchlist'))]) {
            const res = await call();
            expect(res.status).toBe(401);
            expect(await res.json()).toEqual({ error: 'No autenticado' });
        }
    });
});
