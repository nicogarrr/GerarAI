// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Proxy público del feed ICS (/api/calendar-feed/<token>.ics): el token es la
 * credencial, así que un formato ajeno recibe el mismo 404 que uno revocado SIN
 * llamar al backend, y un 5xx/red del backend NUNCA se traduce a 404 (haría
 * parecer revocado un feed sano). El 200 reenvía el ICS con cabeceras de
 * privacidad (noindex, no-referrer, sin caché).
 */
const VALID = `gfc_${'a'.repeat(43)}.ics`;
const params = (token: string) => ({ params: Promise.resolve({ token }) });

// La ruta lee FMP_BACKEND_URL al cargar el módulo (como en el runtime de Next):
// hay que fijarlo ANTES de importarla.
vi.hoisted(() => {
    process.env.FMP_BACKEND_URL = 'http://backend:8000';
});

import { GET } from '@/app/api/calendar-feed/[token]/route';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

beforeEach(() => {
    fetchMock.mockReset();
});
afterEach(() => {
    process.env.FMP_BACKEND_URL = 'http://backend:8000';
});

const upstream = (status: number, body = '') =>
    new Response(body, { status, headers: { 'Content-Type': 'text/calendar' } });

describe('proxy público del feed ICS', () => {
    it('token con formato ajeno: 404 uniforme sin tocar el backend', async () => {
        for (const bad of ['nope', 'gfc_corta.ics', `gfc_${'a'.repeat(43)}.ics/extra`, `gfc_${'a'.repeat(43)}`]) {
            const res = await GET({} as never, params(bad));
            expect(res.status).toBe(404);
        }
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('sin FMP_BACKEND_URL configurado: 503', async () => {
        // La variable se lee al cargar el módulo: reimport limpio sin ella.
        vi.resetModules();
        delete process.env.FMP_BACKEND_URL;
        const { GET: getSinBackend } = await import('@/app/api/calendar-feed/[token]/route');
        const res = await getSinBackend({} as never, params(VALID));
        expect(res.status).toBe(503);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('backend sin red: 503; backend 5xx o 401: 502 (nunca 404)', async () => {
        fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
        expect((await GET({} as never, params(VALID))).status).toBe(503);

        for (const status of [500, 502, 401]) {
            fetchMock.mockResolvedValueOnce(upstream(status));
            expect((await GET({} as never, params(VALID))).status).toBe(502);
        }
    });

    it('404 del backend (token desconocido o revocado): 404', async () => {
        fetchMock.mockResolvedValueOnce(upstream(404));
        expect((await GET({} as never, params(VALID))).status).toBe(404);
    });

    it('200: reenvía el ICS con content-type de calendario y cabeceras de privacidad', async () => {
        fetchMock.mockResolvedValueOnce(upstream(200, 'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n'));
        const res = await GET({} as never, params(VALID));
        expect(fetchMock).toHaveBeenCalledWith('http://backend:8000/api/calendar/feed/' + VALID, { cache: 'no-store' });
        expect(res.status).toBe(200);
        expect(res.headers.get('Content-Type')).toBe('text/calendar; charset=utf-8');
        expect(res.headers.get('Cache-Control')).toBe('no-cache');
        expect(res.headers.get('X-Robots-Tag')).toBe('noindex');
        expect(res.headers.get('Referrer-Policy')).toBe('no-referrer');
        expect(await res.text()).toContain('VCALENDAR');
    });
});
