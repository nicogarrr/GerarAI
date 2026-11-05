import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// El cliente firma la identidad con RESEARCH_AUTH_SECRET: stub para el test.
process.env.RESEARCH_AUTH_SECRET = process.env.RESEARCH_AUTH_SECRET || 'test-secret-de-32-caracteres-minimo!!';

vi.mock('@/lib/auth/require-user', () => ({
    requireAuthenticatedUser: async () => ({ id: 'tenant-test', email: 't@t.dev' }),
}));

import { researchRequest } from '@/lib/research/client';

describe('logging por llamada al backend de research', () => {
    beforeEach(() => {
        vi.spyOn(console, 'info').mockImplementation(() => {});
    });
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it('una línea con método, ruta, status y ms por request OK', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })));
        await researchRequest('/api/companies/CHTR/ttm');
        const info = vi.mocked(console.info);
        expect(info).toHaveBeenCalledTimes(1);
        expect(info.mock.calls[0][0]).toMatch(/^\[research-api\] GET \/api\/companies\/CHTR\/ttm 200 \d+ms$/);
    });

    it('también loguea el fallo (timeout/abort) antes de lanzar', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => {
          throw new DOMException('The operation timed out.', 'TimeoutError');
        }));
        await expect(researchRequest('/api/companies/CHTR/facts?limit=250')).rejects.toThrow(/no disponible|unavailable/i);
        const info = vi.mocked(console.info);
        expect(info).toHaveBeenCalledTimes(1);
        expect(info.mock.calls[0][0]).toMatch(/^\[research-api\] GET \/api\/companies\/CHTR\/facts\?limit=250 timeout de \d+ ms \d+ms$/);
    });

    it('un 500 se loguea con su status antes de responseError', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"boom"}', { status: 500 })));
        await expect(researchRequest('/api/companies/CHTR/share-capital')).rejects.toThrow();
        expect(vi.mocked(console.info).mock.calls[0][0]).toMatch(/^\[research-api\] GET \/api\/companies\/CHTR\/share-capital 500 \d+ms$/);
    });
});
