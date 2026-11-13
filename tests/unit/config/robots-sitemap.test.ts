import { describe, expect, it } from 'vitest';

import robots from '../../../app/robots';
import sitemap from '../../../app/sitemap';
import { siteUrl } from '@/lib/config/site';

// robots.txt y sitemap.xml deben compartir el mismo origen: si el sitemap
// dice https://gerarai.duckdns.org/sitemap.xml pero robots dice otro dominio,
// los buscadores reciben señales contradictorias.

describe('robots y sitemap', () => {
    it('el sitemap que declara robots usa el mismo origen que el sitemap', () => {
        const r = robots();
        const s = sitemap();
        const declared = r.sitemap;
        expect(declared).toBe(`${siteUrl()}/sitemap.xml`);
        for (const entry of s) {
            expect(entry.url).toMatch(new RegExp(`^${siteUrl().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`));
        }
    });

    it('el sitemap solo contiene rutas públicas', () => {
        const urls = sitemap().map((e) => e.url.replace(siteUrl(), ''));
        expect(urls).toContain('/');
        expect(urls).toContain('/metodologia');
        expect(urls).toContain('/help');
        // Ninguna ruta autenticada.
        const private_ = ['/portfolio', '/screener', '/propicks', '/calendar', '/taxes', '/research'];
        for (const p of private_) {
            expect(urls.some((u) => u.startsWith(p))).toBe(false);
        }
    });

    it('robots permite las públicas y bloquea las privadas', () => {
        const rules = robots().rules;
        const rule = Array.isArray(rules) ? rules[0] : rules;
        expect(rule?.allow).toContain('/');
        expect(rule?.disallow).toContain('/portfolio');
        expect(rule?.disallow).toContain('/screener');
        expect(rule?.disallow).toContain('/taxes');
    });
});
