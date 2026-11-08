/**
 * The master stores the exchange as the provider's long English string
 * ("NASDAQ NMS - GLOBAL MARKET") and the search dialog rendered it raw.
 * searchMasterCompanies must normalize it via exchangeDisplayName: known
 * markets become readable labels, unmapped strings stay as-is (honest
 * fallback), and UNKNOWN/empty become absence ('').
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exchangeDisplayName } from '@/lib/exchangeName';

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

const searchWithMaster = async (results: unknown[]) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(masterPayload(results)));
    fetchJSON.mockRejectedValue(new Error('provider quota exhausted'));
    const { searchStocksWithStatus } = await loadModule();
    return searchStocksWithStatus('x');
};

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

describe('searchStocksWithStatus: exchange labels from the master', () => {
    it('maps the long provider string to the readable market name', async () => {
        const res = await searchWithMaster([
            { ticker: 'PARA', name: 'PARAMOUNT GLOBAL', exchange: 'NASDAQ NMS - GLOBAL MARKET', currency: 'USD' },
            { ticker: 'V', name: 'VISA INC', exchange: 'NEW YORK STOCK EXCHANGE, INC.', currency: 'USD' },
        ]);
        expect(res.status).toBe('ok');
        expect(res.stocks.find((s) => s.symbol === 'PARA')?.exchange).toBe('NASDAQ');
        expect(res.stocks.find((s) => s.symbol === 'V')?.exchange).toBe('NYSE');
    });

    it('keeps an unmapped exchange string as-is instead of inventing one', async () => {
        const res = await searchWithMaster([
            { ticker: 'SBUX', name: 'STARBUCKS', exchange: 'SAUDI EXCHANGE', currency: 'SAR' },
        ]);
        expect(res.stocks.find((s) => s.symbol === 'SBUX')?.exchange).toBe('SAUDI EXCHANGE');
    });

    it('treats UNKNOWN and empty exchange as absence, never as a label', async () => {
        const res = await searchWithMaster([
            { ticker: 'AAA', name: 'AAA CORP', exchange: 'UNKNOWN', currency: 'USD' },
            { ticker: 'BBB', name: 'BBB CORP', currency: 'USD' },
        ]);
        expect(res.stocks.find((s) => s.symbol === 'AAA')?.exchange).toBe('');
        expect(res.stocks.find((s) => s.symbol === 'BBB')?.exchange).toBe('');
    });
});

describe('exchangeDisplayName', () => {
    it('covers NYSE Arca and Cboe-style provider strings', () => {
        expect(exchangeDisplayName('NYSE ARCA')).toBe('NYSE Arca');
        expect(exchangeDisplayName('CBOE BZX EXCHANGE')).toBe('Cboe');
        expect(exchangeDisplayName('BATS EXCHANGE')).toBe('Cboe');
    });
});
