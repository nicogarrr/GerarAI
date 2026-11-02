import { beforeEach, expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({ fetch:vi.fn(),identity:vi.fn() }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders:m.identity }));
import { proxyZipDownload } from '@/lib/research/zip-proxy';
const args = { path:'/api/obsidian/vault.zip',filename:'vault.zip',exportErrorDetail:'unavailable',notFoundDetail:'no archive' };
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal('fetch',m.fetch); m.identity.mockResolvedValue({ 'X-Signed':'private' }); });
it('returns bytes with private attachment headers, never the identity', async () => {
    m.fetch.mockResolvedValue(new Response(new Uint8Array([80,75,3,4])));
    const response = await proxyZipDownload(args);
    expect([...new Uint8Array(await response.arrayBuffer())]).toEqual([80,75,3,4]);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(response.headers.get('content-disposition')).toContain('vault.zip');
    expect(response.headers.get('X-Signed')).toBeNull();
    expect(m.identity).toHaveBeenCalledWith({ method:'GET',path:args.path });
    expect(m.fetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
});
it('keeps 404 and upstream failures distinct from interrupted downloads', async () => {
    m.fetch.mockResolvedValueOnce(new Response('',{ status:404 }));
    expect((await proxyZipDownload(args)).status).toBe(404);
    m.fetch.mockResolvedValueOnce(new Response('',{ status:503 }));
    expect((await proxyZipDownload(args)).status).toBe(503);
    m.fetch.mockRejectedValueOnce(new Error('network'));
    expect((await proxyZipDownload(args)).status).toBe(502);
    m.fetch.mockResolvedValueOnce({ ok:true,status:200,arrayBuffer:async () => { throw new Error('truncated'); } });
    expect((await proxyZipDownload(args)).status).toBe(502);
});
