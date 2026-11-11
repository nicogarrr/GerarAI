import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, parseYahooQuote, cacheArgs } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(async () => ({ id: 'user-1' })),
    parseYahooQuote: vi.fn<(...args: any[]) => any>(),
    cacheArgs: [] as unknown[][],
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/cache/memoryTTL', () => ({
    cachedFetch: (...args: unknown[]) => { cacheArgs.push(args); return (args[1] as () => Promise<unknown>)(); },
}));
vi.mock('@/lib/market/live-quotes', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/lib/market/live-quotes')>(),
    LIVE_QUOTE_GROUPS: [
        { key: 'indices', specs: [{ symbol: '^GSPC' }, { symbol: '^IBEX' }] },
        { key: 'divisas', specs: [{ symbol: 'EURUSD=X' }] },
    ],
    parseYahooQuote,
    yahooChartRequest: (symbol: string) => ({ url: `http://yahoo/${encodeURIComponent(symbol)}`, init: {} }),
}));

const fetchMock = vi.fn<(...args: any[]) => any>();
vi.stubGlobal('fetch', fetchMock);

import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';

beforeEach(() => {
    vi.clearAllMocks();
    cacheArgs.length = 0;
});

describe('getLiveMarkets', () => {
    it('un símbolo caído llega null y no tumba los demás (N/D por fila)', async () => {
        fetchMock.mockImplementation(async (url: string) => {
            if (String(url).includes('GSPC')) return { ok: true, json: async () => ({ chart: { result: [{ meta: { regularMarketPrice: 6000 } }] } }) } as Response;
            return { ok: false } as Response; // IBEX y EURUSD caídos
        });
        parseYahooQuote.mockReturnValue({ price: 6000 });
        const result = await getLiveMarkets();
        const [indices, divisas] = result.groups;
        expect(indices.quotes[0]).toEqual({ price: 6000 });
        expect(indices.quotes[1]).toBeNull();
        expect(divisas.quotes[0]).toBeNull();
        expect(typeof result.fetchedAt).toBe('number');
    });

    it('fallo total lanza, no es una actualización válida', async () => {
        fetchMock.mockRejectedValue(new Error('timeout'));
        await expect(getLiveMarkets()).rejects.toThrow('live_quotes_unavailable');
    });

    it('respuesta sin meta -> parseYahooQuote recibe null y decide', async () => {
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({ chart: { result: [] } }) } as unknown as Response);
        parseYahooQuote.mockReturnValue(null);
        await expect(getLiveMarkets()).rejects.toThrow('live_quotes_unavailable');
        expect(parseYahooQuote).toHaveBeenCalledWith(expect.objectContaining({ symbol: '^GSPC' }), null, expect.anything());
    });

    it('usa la caché compartida con TTL 55 (bajo el poll de 60 s)', async () => {
        fetchMock.mockResolvedValue({ ok: true, json: async () => ({ chart: { result: [{ meta: {} }] } }) } as unknown as Response);
        parseYahooQuote.mockReturnValue({ price: 6000 });
        await getLiveMarkets();
        expect(cacheArgs[0][0]).toBe('live-markets:v2');
        expect(cacheArgs[0][2]).toBe(55);
    });
});
