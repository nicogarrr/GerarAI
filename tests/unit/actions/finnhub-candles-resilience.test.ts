import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, fetchJSON, researchIdentityHeaders } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    fetchJSON: vi.fn(),
    researchIdentityHeaders: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders }));

const loadModule = async (apiKey?: string) => {
    vi.resetModules();
    if (apiKey === undefined) delete process.env.FINNHUB_API_KEY;
    else process.env.FINNHUB_API_KEY = apiKey;
    return import('@/lib/actions/finnhub.actions');
};

beforeEach(() => {
    vi.clearAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    researchIdentityHeaders.mockResolvedValue({});
    process.env.FMP_BACKEND_URL = 'https://backend.internal';
});

afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.FINNHUB_API_KEY;
    delete process.env.FMP_BACKEND_URL;
});

const okPayload = { s: 'ok', c: [10, 11], t: [1, 2], o: [9, 10], h: [12, 13], l: [8, 9], v: [100, 200] };

const okResponse = () => ({ ok: true, json: async () => okPayload });
const failResponse = () => ({ ok: false, json: async () => ({}) });

describe('getCandles: un abort de 8 s no deja la ficha sin velas (5-nov-2026)', () => {
    it('reintenta una vez con más margen si el primer intento al backend aborta', async () => {
        const { getCandles } = await loadModule(undefined);
        const fetchMock = vi.fn()
            .mockRejectedValueOnce(new DOMException('The operation timed out', 'TimeoutError'))
            .mockResolvedValueOnce(okResponse());
        vi.stubGlobal('fetch', fetchMock);
        const result = await getCandles('CHTR', 1_730_000_000, 1_762_000_000);
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(result.s).toBe('ok');
        expect(result.c).toEqual([10, 11]);
    });

    it('sirve el último dato bueno si Finnhub y los dos intentos al backend fallan', async () => {
        const { getCandles } = await loadModule(undefined);
        const fetchMock = vi.fn().mockResolvedValue(okResponse());
        vi.stubGlobal('fetch', fetchMock);
        const first = await getCandles('CHTR', 1_730_000_000, 1_762_000_000);
        expect(first.s).toBe('ok');
        expect(fetchMock).toHaveBeenCalledTimes(1);

        fetchMock.mockReset().mockRejectedValue(new Error('backend caído'));
        const second = await getCandles('CHTR', 1_730_000_000, 1_762_000_000);
        expect(fetchMock).toHaveBeenCalledTimes(2); // intento + reintento
        expect(second.s).toBe('ok');
        expect(second.c).toEqual([10, 11]);
    });

    it('sin dato bueno previo y con todo caído devuelve no_data (estado honesto)', async () => {
        const { getCandles } = await loadModule(undefined);
        const fetchMock = vi.fn().mockResolvedValue(failResponse());
        vi.stubGlobal('fetch', fetchMock);
        const result = await getCandles('CHTR', 1_730_000_000, 1_762_000_000);
        expect(result.s).toBe('no_data');
        expect(result.c).toEqual([]);
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('un 403 de Finnhub cae al fallback y lo cachea para la siguiente', async () => {
        const { getCandles } = await loadModule('key');
        fetchJSON.mockRejectedValue(new Error('403'));
        const fetchMock = vi.fn().mockResolvedValue(okResponse());
        vi.stubGlobal('fetch', fetchMock);
        const first = await getCandles('CHTR', 1_730_000_000, 1_762_000_000);
        expect(first.source).toBe('Yahoo Finance');
        fetchMock.mockReset().mockRejectedValue(new Error('caído'));
        fetchJSON.mockRejectedValue(new Error('403'));
        const second = await getCandles('CHTR', 1_730_000_000, 1_762_000_000);
        expect(second.s).toBe('ok');
        expect(second.c).toEqual([10, 11]);
    });
});
