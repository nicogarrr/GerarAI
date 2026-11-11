import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { requestCache } from '@/lib/cache/requestCache';
import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';

vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn(async () => ({ id: 'fixture' })) }));
vi.mock('@/lib/market/live-quotes', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/lib/market/live-quotes')>(),
    LIVE_QUOTE_GROUPS: [{ key: 'indice', specs: [{ symbol: 'LOCAL', name: 'Local fixture', kind: 'indice', unit: 'index', decimals: 2 }] }],
    yahooChartRequest: () => ({ url: 'https://fixture.invalid/quote', init: {} }),
}));

beforeEach(() => requestCache.clear());
afterEach(() => { requestCache.clear(); vi.unstubAllGlobals(); });

it('does not cache a total outage as success: an immediate recovery reads the provider again', async () => {
    const fetcher = vi.fn()
        .mockResolvedValueOnce({ ok: false })
        .mockResolvedValue({ ok: true, json: async () => ({ chart: { result: [{ meta: { regularMarketPrice: 123, regularMarketTime: 1_800_000_000 } }] } }) });
    vi.stubGlobal('fetch', fetcher);
    await expect(getLiveMarkets()).rejects.toThrow('live_quotes_unavailable');
    const recovered = await getLiveMarkets();
    expect(recovered.groups[0].quotes[0]?.price).toBe(123);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(await getLiveMarkets()).toEqual(recovered);
    expect(fetcher).toHaveBeenCalledTimes(2);
});
