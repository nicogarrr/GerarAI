import { afterEach, describe, expect, it, vi } from 'vitest';

// Auditoría #2973: el Dockerfile declara `ARG NEXT_PUBLIC_*` + `ENV X=$X`; sin
// --build-arg la variable llega vacía ("") y `.url()`/`.email()` tumbaban el
// `npm run build` de la imagen. Vacía debe valer lo mismo que no configurada.
describe('lib/env con variables públicas vacías', () => {
    afterEach(() => {
        vi.unstubAllEnvs();
        vi.resetModules();
    });

    it.each([
        ['build', { NEXT_PHASE: 'phase-production-build' }],
        ['runtime', {}],
    ])('no falla en %s y las trata como no configuradas', async (_phase, extra) => {
        for (const [key, value] of Object.entries(extra)) vi.stubEnv(key, value);
        vi.stubEnv('NEXT_PUBLIC_SITE_URL', '');
        vi.stubEnv('NEXT_PUBLIC_SUPPORT_EMAIL', '');
        vi.stubEnv('NEXT_PUBLIC_APP_URL', '');
        vi.resetModules();
        const { env } = await import('@/lib/env');
        expect(env.NEXT_PUBLIC_SITE_URL).toBeUndefined();
        expect(env.NEXT_PUBLIC_SUPPORT_EMAIL).toBeUndefined();
    });

    it('sigue rechazando una URL mal formada', async () => {
        vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'no-es-una-url');
        vi.resetModules();
        await expect(import('@/lib/env')).rejects.toThrow(/NEXT_PUBLIC_SITE_URL/);
    });
});
