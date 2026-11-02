import { beforeEach, expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({ identity: vi.fn(), fetch: vi.fn() }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders: m.identity }));
import { proxyResearchPost } from '@/lib/research/post-proxy';
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal('fetch',m.fetch); m.identity.mockResolvedValue({ 'X-Signature': 'signed' }); });
it('signs the exact POST body and keeps a deadline without exposing identity', async () => {
    m.fetch.mockResolvedValue(new Response(JSON.stringify({ translated: 'hola' })));
    const body = JSON.stringify({ headline: 'hello' });
    const response = await proxyResearchPost({ path: '/api/news/translate-headline',timeoutMs:12000,body });
    expect(m.identity).toHaveBeenCalledWith({ method:'POST',path:'/api/news/translate-headline',body });
    expect(m.fetch.mock.calls[0][1]).toMatchObject({ method:'POST',body,cache:'no-store',headers:{ 'X-Signature':'signed','Content-Type':'application/json' } });
    expect(m.fetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    expect(await response.json()).toEqual({ translated:'hola' });
    expect(response.headers.get('X-Signature')).toBeNull();
});
it('preserves upstream status and returns an honest 502 for network or bad JSON', async () => {
    m.fetch.mockResolvedValueOnce(new Response('',{ status:429 }));
    expect((await proxyResearchPost({ path:'/api/news/1/translation',timeoutMs:12000 })).status).toBe(429);
    m.fetch.mockRejectedValueOnce(new Error('network'));
    expect((await proxyResearchPost({ path:'/api/news/1/translation',timeoutMs:12000 })).status).toBe(502);
    m.fetch.mockResolvedValueOnce(new Response('invalid JSON'));
    expect((await proxyResearchPost({ path:'/api/news/1/translation',timeoutMs:12000 })).status).toBe(502);
});
