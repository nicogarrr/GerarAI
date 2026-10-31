import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn().mockResolvedValue({}) }));
vi.mock('@/lib/auth/route-auth', () => ({ withAuthErrors: (h: unknown) => h }));

const fetchSiteIconMock = vi.fn();
vi.mock('@/lib/logos/site-icon', async (importOriginal) => {
    const original = await importOriginal<typeof import('@/lib/logos/site-icon')>();
    return { ...original, fetchSiteIcon: (...args: unknown[]) => fetchSiteIconMock(...args) };
});

import { GET } from '@/app/api/logo/[ticker]/route';
import { LOGO_TOTAL_BUDGET_MS } from '@/lib/logos/logo-budget';

const paramsOf = (ticker: string) => Promise.resolve({ ticker });

describe('GET /api/logo/[ticker]: presupuesto total de latencia', () => {
    beforeEach(() => {
        fetchSiteIconMock.mockReset();
    });

    it('un icono que cuelga el fetch se corta por el presupuesto y responde 404 cacheable', async () => {
        // fetchSiteIcon respeta la señal compuesta que le llega por init.signal
        fetchSiteIconMock.mockImplementation(async (_domain: string, fetchImpl: typeof fetch) => {
            try {
                await fetchImpl('https://aena.es/', { signal: AbortSignal.timeout(60_000) });
            } catch {
                return null;
            }
            return null;
        });
        const t0 = Date.now();
        const res = await GET(new Request('https://x/api/logo/AENA'), { params: paramsOf('AENA') });
        const elapsed = Date.now() - t0;
        expect(res.status).toBe(404);
        expect(res.headers.get('Cache-Control')).toContain('max-age=3600');
        expect(elapsed).toBeLessThan(LOGO_TOTAL_BUDGET_MS + 1500);
    }, 15_000);

    it('un icono rápido se sirve con su content-type y caché larga', async () => {
        fetchSiteIconMock.mockResolvedValue({ bytes: new Uint8Array([1, 2, 3]), contentType: 'image/png' });
        const res = await GET(new Request('https://x/api/logo/TSLA'), { params: paramsOf('TSLA') });
        expect(res.status).toBe(200);
        expect(res.headers.get('Content-Type')).toBe('image/png');
        expect(res.headers.get('Cache-Control')).toContain('max-age=86400');
    });
});
