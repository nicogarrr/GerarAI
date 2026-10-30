/**
 * El buscador (searchStocksWithStatus) usa el master propio como primera
 * fuente: con la cuota free de Finnhub agotada (429) o el proveedor lento,
 * «Amzn» mostraba «fallo del proveedor de datos» pese a tener AMAZON en
 * nuestro registro (reporte de Nico, 2026-10-30 01:09).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, fetchJSON, researchIdentityHeaders } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    fetchJSON: vi.fn(),
    researchIdentityHeaders: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_k: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/actions/newsSources.actions', () => ({ getNewsWithFallback: vi.fn() }));

const loadModule = async () => {
    vi.resetModules();
    process.env.FINNHUB_API_KEY = 'key';
    process.env.FMP_BACKEND_URL = 'https://backend.test';
    return import('@/lib/actions/finnhub.actions');
};

const masterPayload = (results: unknown[]) => ({
    ok: true,
    json: async () => ({ results }),
});

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    researchIdentityHeaders.mockResolvedValue({});
});

afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.FINNHUB_API_KEY;
    delete process.env.FMP_BACKEND_URL;
});

describe('searchStocksWithStatus con master propio', () => {
    it('master primero, Finnhub despues, sin duplicar el mismo simbolo', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(masterPayload([
            { ticker: 'AMZN', name: 'AMAZON.COM INC (MASTER)', exchange: 'NASDAQ', currency: 'USD' },
        ])));
        fetchJSON.mockResolvedValue({
            result: [
                { symbol: 'AMZN', displaySymbol: 'AMZN', description: 'AMAZON.COM INC', type: 'Common Stock' },
                { symbol: 'AMZN.L', displaySymbol: 'AMZN.L', description: 'LS 1X AMZN', type: 'ETP' },
            ],
        });
        const { searchStocksWithStatus } = await loadModule();

        const res = await searchStocksWithStatus('Amzn');

        expect(res.status).toBe('ok');
        expect(res.stocks[0].symbol).toBe('AMZN');
        expect(res.stocks[0].name).toBe('AMAZON.COM INC (MASTER)');
        expect(res.stocks.map((s) => s.symbol)).toContain('AMZN.L');
        expect(res.stocks.filter((s) => s.symbol === 'AMZN')).toHaveLength(1);
    });

    it('Finnhub 429 pero el master tiene la empresa -> ok con resultados del master', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(masterPayload([
            { ticker: 'AMZN', name: 'AMAZON.COM INC', exchange: 'NASDAQ', currency: 'USD' },
        ])));
        fetchJSON.mockRejectedValue(new Error('API rate limit reached'));
        const { searchStocksWithStatus } = await loadModule();

        const res = await searchStocksWithStatus('Amzn');

        expect(res.status).toBe('ok');
        expect(res.stocks.map((s) => s.symbol)).toEqual(['AMZN']);
    });

    it('Finnhub caido y master sin coincidencias ni local -> error honesto', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(masterPayload([])));
        fetchJSON.mockRejectedValue(new Error('API rate limit reached'));
        const { searchStocksWithStatus } = await loadModule();

        const res = await searchStocksWithStatus('xyzzynoexiste');

        expect(res).toEqual({ status: 'error', stocks: [] });
    });

    it('master inaccesible -> el resultado de Finnhub sigue funcionando', async () => {
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('backend caido')));
        fetchJSON.mockResolvedValue({
            result: [{ symbol: 'AMZN', displaySymbol: 'AMZN', description: 'AMAZON.COM INC', type: 'Common Stock' }],
        });
        const { searchStocksWithStatus } = await loadModule();

        const res = await searchStocksWithStatus('Amzn');

        expect(res.status).toBe('ok');
        expect(res.stocks[0].symbol).toBe('AMZN');
    });

    it('la consulta al master va plegada (sin acentos) y acotada', async () => {
        const fetchMock = vi.fn().mockResolvedValue(masterPayload([]));
        vi.stubGlobal('fetch', fetchMock);
        fetchJSON.mockResolvedValue({ result: [] });
        const { searchStocksWithStatus } = await loadModule();

        await searchStocksWithStatus('Telefónica ');

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[0][0]).toContain('/api/companies/search?q=Telefonica&limit=15');
    });
});
