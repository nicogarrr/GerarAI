import { afterEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ tenant: 'tenant-a' }));
vi.mock('@/lib/auth/research-identity', () => ({
    normalizeResearchBody: async (body: unknown) => ({ body }),
    researchIdentityHeaders: async () => ({ 'X-CavaAI-Tenant': state.tenant, 'X-CavaAI-User': state.tenant, 'X-CavaAI-Nonce': Math.random().toString() }),
}));
import { researchRequest } from '@/lib/research/client';
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); state.tenant = 'tenant-a'; });
const limited = (wait: string) => new Response('{"detail":"Rate limit exceeded"}', { status: 429, headers: { 'Retry-After': wait } });
it.each(['120', '0', '-1', 'garbage', ''])('never retries before a safe complete Retry-After (%s)', async (wait) => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementation(async () => limited(wait));
    vi.stubGlobal('fetch', fetcher);
    const result = researchRequest('/api/companies/UBER/snapshot').catch(error => error);
    await vi.advanceTimersByTimeAsync(6000);
    expect(((await result) as { statusCode: number }).statusCode).toBe(429);
    expect(fetcher).toHaveBeenCalledTimes(1);
});
it('honors the whole positive Retry-After and retries at most once', async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementation(async () => limited('6'));
    vi.stubGlobal('fetch', fetcher);
    const result = researchRequest('/api/retry-six', { timeoutMs: 10000 }).catch(error => error);
    await vi.advanceTimersByTimeAsync(5900);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(((await result) as { statusCode: number }).statusCode).toBe(429);
    expect(fetcher).toHaveBeenCalledTimes(2);
});
it('coalesces concurrent identical signed GETs, each caller receives its own parsed body', async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>(resolve => { release = resolve; });
    const fetcher = vi.fn().mockReturnValue(pending);
    vi.stubGlobal('fetch', fetcher);
    const first = researchRequest<{ ok: boolean }>('/api/dedupe');
    const second = researchRequest<{ ok: boolean }>('/api/dedupe');
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalled());
    release(new Response('{"ok":true}'));
    const [a, b] = await Promise.all([first, second]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
    expect(a).not.toBe(b);
    fetcher.mockResolvedValue(new Response('{"ok":false}'));
    expect(await researchRequest('/api/dedupe')).toEqual({ ok: false });
    expect(fetcher).toHaveBeenCalledTimes(2);
});
it('never coalesces different verified tenants while both reads are pending', async () => {
    const releases: Array<(response: Response) => void> = [];
    const fetcher = vi.fn().mockImplementation(() => new Promise<Response>(resolve => releases.push(resolve)));
    vi.stubGlobal('fetch', fetcher);
    const a = researchRequest('/api/tenant-isolated');
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    state.tenant = 'tenant-b';
    const b = researchRequest('/api/tenant-isolated');
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    releases[0](new Response('{"tenant":"a"}'));
    releases[1](new Response('{"tenant":"b"}'));
    expect(await a).toEqual({ tenant: 'a' });
    expect(await b).toEqual({ tenant: 'b' });
});
it('never merges different query strings or language headers', async () => {
    const releases: Array<(response: Response) => void> = [];
    const fetcher = vi.fn().mockImplementation(() => new Promise<Response>(resolve => releases.push(resolve)));
    vi.stubGlobal('fetch', fetcher);
    const reads = [researchRequest('/api/distinct?q=1'), researchRequest('/api/distinct?q=2'),
      researchRequest('/api/distinct?q=1', { headers: { 'Accept-Language': 'en' } })];
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    for (const release of releases) release(new Response('{}'));
    await Promise.all(reads);
});
it('removes a failed pending read instead of caching its rejection', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('network')).mockResolvedValue(new Response('{"ok":true}'));
    vi.stubGlobal('fetch', fetcher);
    await expect(researchRequest('/api/recover')).rejects.toThrow();
    expect(await researchRequest('/api/recover')).toEqual({ ok: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
});
it('does not coalesce independently abortable calls or writes', async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetcher);
    await Promise.all([researchRequest('/api/abort', { signal: new AbortController().signal }), researchRequest('/api/abort', { signal: new AbortController().signal })]);
    await Promise.all([researchRequest('/api/write', { method: 'POST' }), researchRequest('/api/write', { method: 'POST' })]);
    expect(fetcher).toHaveBeenCalledTimes(4);
});
