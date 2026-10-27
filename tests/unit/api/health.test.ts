import { describe, expect, it } from 'vitest';
import { GET } from '@/app/api/health/route';

describe('GET /api/health', () => {
    it('responde 200 con un estado vivo en JSON, sin caché', async () => {
        const res = await GET();
        expect(res.status).toBe(200);
        expect(res.headers.get('Cache-Control')).toBe('no-store');
        const body = await res.json();
        expect(body.estado).toBe('ok');
        // Marca temporal ISO que demuestra que el proceso responde ahora.
        expect(typeof body.marca).toBe('string');
        expect(Number.isNaN(Date.parse(body.marca))).toBe(false);
    });
});
