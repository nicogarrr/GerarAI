import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchIdentityHeaders, requireAuthenticatedUser } = vi.hoisted(() => ({
    researchIdentityHeaders: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
}));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    getCandles: vi.fn(), getProfile: vi.fn(), getStockQuote: vi.fn(),
}));

import { getResearchCompaniesBasics } from '@/lib/actions/market-workspace.actions';

function mockFetchOnce(payload: unknown, ok = true) {
    const fetchMock = vi.fn().mockResolvedValue({
        ok,
        json: async () => payload,
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
}

beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    researchIdentityHeaders.mockResolvedValue({});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    process.env.FMP_BACKEND_URL = 'https://backend.test';
});

describe('getResearchCompaniesBasics (lote agregado)', () => {
    it('mapea por ticker pedido (normalizado) y deja null los missing', async () => {
        mockFetchOnce({
            items: {
                'SAN.MC': { ticker: 'SAN', name: 'BANCO SANTANDER SA', exchange: 'BME', currency: 'EUR' },
                TSLA: { ticker: 'TSLA', name: 'TESLA INC', exchange: 'NASDAQ', currency: 'USD' },
            },
            missing: ['NOPE'],
        });

        const out = await getResearchCompaniesBasics(['san.mc', 'TSLA', 'NOPE', 'tsla']);

        expect(out).not.toBeNull();
        expect(out!['SAN.MC']?.ticker).toBe('SAN');
        expect(out!['SAN.MC']?.exchange).toBe('BME');
        expect(out!.TSLA?.name).toBe('TESLA INC');
        expect(out!.NOPE).toBeNull();
        expect(Object.keys(out!)).toHaveLength(3);
    });

    it('una sola peticion con todos los tickers en la query', async () => {
        const fetchMock = mockFetchOnce({ items: {}, missing: ['A', 'B'] });
        await getResearchCompaniesBasics(['A', 'B']);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[0][0]).toContain('/api/companies/basics?tickers=A%2CB');
    });

    it('backend sin el agregado (404/500) -> null para caer a la oleada por simbolo', async () => {
        mockFetchOnce({}, false);
        expect(await getResearchCompaniesBasics(['AAPL'])).toBeNull();
    });

    it('fetch que lanza -> null (nunca rompe la pagina)', async () => {
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('red caida')));
        expect(await getResearchCompaniesBasics(['AAPL'])).toBeNull();
    });

    it('payload sin items valido -> null', async () => {
        mockFetchOnce({ items: null });
        expect(await getResearchCompaniesBasics(['AAPL'])).toBeNull();
    });

    it('lista vacia -> {} sin llamar al backend', async () => {
        const fetchMock = mockFetchOnce({});
        expect(await getResearchCompaniesBasics([])).toEqual({});
        expect(fetchMock).not.toHaveBeenCalled();
    });
});
