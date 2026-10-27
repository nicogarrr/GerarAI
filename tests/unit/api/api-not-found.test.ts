import { describe, expect, it } from 'vitest';
import { DELETE, GET, POST } from '@/app/api/[...rest]/route';

describe('rutas de API inexistentes', () => {
    it('GET devuelve 404 en JSON y en español, no el not-found HTML', async () => {
        const res = await GET();
        expect(res.status).toBe(404);
        expect(res.headers.get('Content-Type')).toContain('application/json');
        const body = await res.json();
        expect(body.error).toMatch(/no encontrada/i);
    });

    it('el resto de métodos también devuelven 404 (no 405)', async () => {
        for (const handler of [POST, DELETE]) {
            const res = await handler();
            expect(res.status).toBe(404);
        }
    });
});
