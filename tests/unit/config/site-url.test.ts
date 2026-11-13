import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

// siteUrl(): origen canónico del sitio. Antes sitemap.xml y robots.txt
// repetían la cadena `process.env.X || 'http://localhost:3000'` y un fichero
// usaba `BETTER_AUTH_URL` pero el otro no: el sitemap apuntaba a una URL y
// robots a otra. El test pincha la precedencia (NEXT_PUBLIC_SITE_URL >
// BETTER_AUTH_URL > localhost) y la normalización de barras finales.

const RAW_ENV = { ...process.env };

async function freshSiteUrl() {
    vi.resetModules();
    const mod = await import('@/lib/config/site');
    return mod.siteUrl;
}

beforeEach(() => {
    vi.unstubAllEnvs();
    delete process.env.NEXT_PUBLIC_SITE_URL;
    delete process.env.BETTER_AUTH_URL;
});

afterEach(() => {
    process.env = { ...RAW_ENV };
});

describe('siteUrl', () => {
    it('prioriza NEXT_PUBLIC_SITE_URL sobre BETTER_AUTH_URL', async () => {
        vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://gerarai.duckdns.org');
        vi.stubEnv('BETTER_AUTH_URL', 'https://auth.ejemplo.com');
        const siteUrl = await freshSiteUrl();
        expect(siteUrl()).toBe('https://gerarai.duckdns.org');
    });

    it('cae a BETTER_AUTH_URL si no hay NEXT_PUBLIC_SITE_URL', async () => {
        vi.stubEnv('BETTER_AUTH_URL', 'https://auth.ejemplo.com');
        const siteUrl = await freshSiteUrl();
        expect(siteUrl()).toBe('https://auth.ejemplo.com');
    });

    it('cae a localhost sin ninguna variable', async () => {
        const siteUrl = await freshSiteUrl();
        expect(siteUrl()).toBe('http://localhost:3000');
    });

    it('quita la barra final para que las rutas no salgan con //', async () => {
        vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://gerarai.duckdns.org/');
        const siteUrl = await freshSiteUrl();
        expect(siteUrl()).toBe('https://gerarai.duckdns.org');
    });

    it('quita varias barras finales', async () => {
        vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://gerarai.duckdns.org///');
        const siteUrl = await freshSiteUrl();
        expect(siteUrl()).toBe('https://gerarai.duckdns.org');
    });
});
