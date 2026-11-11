import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { authenticate, cacheRead, specs } = vi.hoisted(() => ({
    authenticate: vi.fn(async () => ({ id: 'pool-test-user' })),
    cacheRead: vi.fn(),
    specs: Array.from({ length: 13 }, (_, i) => ({
        symbol: `LOCAL${i}`, name: `Fixture ${i}`, kind: 'accion' as const,
        unit: 'USD' as const, decimals: 2,
    })),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: authenticate }));
vi.mock('@/lib/cache/memoryTTL', () => ({
    cachedFetch: (key: string, read: () => Promise<unknown>, ttl: number) => {
        cacheRead(key, ttl);
        return read();
    },
}));
vi.mock('@/lib/market/live-quotes', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/lib/market/live-quotes')>(),
    LIVE_QUOTE_GROUPS: [
        { key: 'accion', specs: specs.slice(0, 7) },
        { key: 'materia', specs: specs.slice(7) },
    ],
    yahooChartRequest: (symbol: string) => ({ url: `https://fixture.invalid/${symbol}`, init: {} }),
}));

import { getLiveMarkets } from '@/lib/actions/live-quotes.actions';

function response(index: number): Response {
    return {
        ok: true,
        json: async () => ({ chart: { result: [{ meta: {
            regularMarketPrice: index + 100, regularMarketTime: 1_800_000_000,
            currency: 'USD', exchangeName: 'TEST', instrumentType: 'EQUITY',
        } }] } }),
    } as Response;
}

beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(0);
    authenticate.mockResolvedValue({ id: 'pool-test-user' });
});
afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe('live quote bounded work queue', () => {
    it('starts the next symbol in a freed slot, without waiting for the slowest batch member', async () => {
        const pending = new Map<number, (value: Response) => void>();
        vi.stubGlobal('fetch', vi.fn((url: string) => {
            const index = Number(url.split('LOCAL')[1]);
            return new Promise<Response>((resolve) => pending.set(index, resolve));
        }));
        const result = getLiveMarkets();
        await vi.advanceTimersByTimeAsync(0);
        expect([...pending.keys()]).toEqual([0, 1, 2, 3, 4, 5]);
        pending.get(1)!(response(1));
        await vi.advanceTimersByTimeAsync(0);
        try {
            expect(pending.has(6)).toBe(true);
            expect(pending.has(7)).toBe(false);
        } finally {
            // Drain even when run against the red baseline: leave no pending work.
            for (let i = 0; i < specs.length; i += 1) {
                for (const [index, resolve] of pending) resolve(response(index));
                await vi.advanceTimersByTimeAsync(0);
            }
            await result;
        }
    });

    it('keeps all symbols in catalog order, six requests max, and completes the same synthetic schedule in 1010ms', async () => {
        let active = 0;
        let maximum = 0;
        const seen: number[] = [];
        vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => {
            expect(init.cache).toBe('no-store');
            expect(init.signal).toBeInstanceOf(AbortSignal);
            const index = Number(url.split('LOCAL')[1]);
            seen.push(index);
            active += 1;
            maximum = Math.max(maximum, active);
            return new Promise<Response>((resolve) => setTimeout(() => {
                active -= 1;
                resolve(response(index));
            }, index === 0 || index === 6 ? 1000 : 10));
        }));
        const started = Date.now();
        let completedAt: number | null = null;
        const result = getLiveMarkets().then((value) => {
            completedAt = Date.now() - started;
            return value;
        });
        await vi.runAllTimersAsync();
        const payload = await result;
        expect(completedAt).toBe(1010);
        expect(maximum).toBe(6);
        expect(active).toBe(0);
        expect(seen).toEqual(specs.map((_, index) => index));
        expect(payload.groups.map((group) => group.key)).toEqual(['accion', 'materia']);
        expect(payload.groups.flatMap((group) => group.quotes).map((quote) => quote?.symbol)).toEqual(specs.map((spec) => spec.symbol));
        expect(payload.groups.flatMap((group) => group.quotes).map((quote) => quote?.price)).toEqual(specs.map((_, index) => index + 100));
        expect(cacheRead).toHaveBeenCalledWith('live-markets:v2', 55);
        expect(authenticate).toHaveBeenCalledOnce();
    });

    it('continues after network/HTTP/JSON/parse failures and preserves null slots without retries', async () => {
        vi.stubGlobal('fetch', vi.fn(async (url: string) => {
            const index = Number(url.split('LOCAL')[1]);
            if (index === 0) throw new Error('network fixture');
            if (index === 1) return { ok: false } as Response;
            if (index === 6) return { ok: true, json: async () => { throw new Error('bad JSON'); } } as unknown as Response;
            if (index === 7) return { ok: true, json: async () => ({ chart: { result: [] } }) } as unknown as Response;
            return response(index);
        }));
        const payload = await getLiveMarkets();
        expect(fetch).toHaveBeenCalledTimes(13);
        expect(payload.groups.flatMap((group) => group.quotes).map((quote) => quote?.symbol ?? null)).toEqual(specs.map((spec, index) => [0, 1, 6, 7].includes(index) ? null : spec.symbol));
    });

    it('does not read the cache or start any quote request if authentication fails', async () => {
        authenticate.mockRejectedValueOnce(new Error('unauthorized'));
        vi.stubGlobal('fetch', vi.fn());
        await expect(getLiveMarkets()).rejects.toThrow('unauthorized');
        expect(cacheRead).not.toHaveBeenCalled();
        expect(fetch).not.toHaveBeenCalled();
    });
});
