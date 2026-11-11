import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ auth: vi.fn(), fetch: vi.fn(), env: { FINNHUB_API_KEY: 'test-key' as string | undefined } }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: mocks.auth }));
vi.mock('@/lib/env', () => ({ env: mocks.env }));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON: mocks.fetch }));
import { getStockPerMetric } from '@/lib/actions/company-per-metric.actions';
import { getCompanyPer } from '@/lib/actions/company-per.actions';
beforeEach(() => { vi.clearAllMocks(); mocks.env.FINNHUB_API_KEY = 'test-key'; mocks.auth.mockResolvedValue({ id: 'u' }); mocks.fetch.mockResolvedValue({ metric: { peTTM: 23 } }); });
it('PER requests only metric, normalizes/encodes symbol, retains daily TTL', async () => {
    expect(await getCompanyPer(' aapl ', { exchange: 'NASDAQ', currency: 'USD' })).toMatchObject({ value: 23 });
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(mocks.fetch).toHaveBeenCalledWith('https://finnhub.io/api/v1/stock/metric?symbol=AAPL&metric=all&token=test-key', 86400);
    await getStockPerMetric('a&b');
    expect(mocks.fetch.mock.calls[1][0]).toContain('symbol=A%26B');
});
it('non-US and missing quote line never query another listing', async () => {
    expect((await getCompanyPer('ASML', { exchange: 'AMS', currency: 'EUR' })).value).toBeNull();
    expect(mocks.fetch).not.toHaveBeenCalled();
});
it('missing key, provider error and absent metric remain unknown, never zero', async () => {
    mocks.env.FINNHUB_API_KEY = undefined;
    expect(await getStockPerMetric('AAPL')).toBeNull();
    expect(mocks.fetch).not.toHaveBeenCalled();
    mocks.env.FINNHUB_API_KEY = 'test-key';
    mocks.fetch.mockRejectedValueOnce(new Error('429'));
    expect((await getCompanyPer('AAPL', { exchange: 'NASDAQ', currency: 'USD' })).value).toBeNull();
    mocks.fetch.mockResolvedValueOnce({});
    expect((await getCompanyPer('AAPL', { exchange: 'NASDAQ', currency: 'USD' })).value).toBeNull();
});
it('authentication rejection is not swallowed and never contacts provider', async () => {
    mocks.auth.mockRejectedValue(new Error('unauthorized'));
    await expect(getStockPerMetric('AAPL')).rejects.toThrow('unauthorized');
    expect(mocks.fetch).not.toHaveBeenCalled();
});
