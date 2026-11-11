import { afterEach, expect, it, vi } from 'vitest';
vi.mock('@/lib/auth/research-identity', () => ({
    normalizeResearchBody: async (body: unknown) => ({ body }),
    researchIdentityHeaders: async () => ({}),
}));
import { requestSignal, researchRequest } from '@/lib/research/client';
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
it('preserves Retry-After from the final GET 429 after its existing single retry', async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn()
        .mockResolvedValueOnce(new Response('{"detail":"Rate limit exceeded"}', { status: 429, headers: { 'Retry-After': '1' } }))
        .mockResolvedValueOnce(new Response('{"detail":"Rate limit exceeded"}', { status: 429, headers: { 'Retry-After': '120' } }));
    vi.stubGlobal('fetch', fetcher);
    const result = researchRequest('/api/companies/MSFT/snapshot').catch(error => error);
    await vi.advanceTimersByTimeAsync(1000);
    const error = await result;
    expect(error).toMatchObject({ statusCode: 429, cause: { path: '/api/companies/MSFT/snapshot', retryAfterSeconds: 120 } });
    expect(fetcher).toHaveBeenCalledTimes(2);
});
it('adds safe cooldown metadata when a non-retried request returns 429 without a header', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('not JSON', { status: 429 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(researchRequest('/api/test', { method: 'POST' })).rejects.toMatchObject({ statusCode: 429, cause: { retryAfterSeconds: 60 } });
    expect(fetcher).toHaveBeenCalledOnce();
});

it('fallback signal composition still aborts while the caller waits to retry', () => {
    const descriptor = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
    Object.defineProperty(AbortSignal, 'any', { configurable: true, value: undefined });
    try {
        const external = new AbortController();
        const combined = requestSignal(external.signal, 10_000);
        external.abort('cancelled');
        expect(combined.aborted).toBe(true);
        expect(combined.reason).toBe('cancelled');
        expect(requestSignal(external.signal, 10_000).aborted).toBe(true);
        const timeout = new AbortController();
        vi.spyOn(AbortSignal, 'timeout').mockReturnValue(timeout.signal);
        const other = new AbortController();
        const timed = requestSignal(other.signal, 10_000);
        timeout.abort('timeout');
        expect(timed.reason).toBe('timeout');
        expect(requestSignal(other.signal, 10_000).aborted).toBe(true);
    } finally {
        if (descriptor) Object.defineProperty(AbortSignal, 'any', descriptor);
        else Reflect.deleteProperty(AbortSignal, 'any');
        vi.restoreAllMocks();
    }
});
