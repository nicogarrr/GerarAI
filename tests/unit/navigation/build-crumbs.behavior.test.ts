import { describe, expect, it } from 'vitest';
import { buildCrumbs } from '@/lib/nav/build-crumbs';
import { NAV_SECTIONS, flattenNavItems } from '@/lib/constants';
import navEs from '@/lib/i18n/messages/es/nav.json';

const labels = (path: string) => buildCrumbs(path).map((crumb) => crumb.labelKey ?? crumb.rawLabel);
const home = { href: '/inicio', labelKey: 'nav.items.inicio' };

describe('breadcrumb route behaviour', () => {
    it.each(['/inicio', '/', '/unknown', '/research-not-a-child', '/portfolio-copy'])('does not invent an anchor for %s', (path) => {
        expect(buildCrumbs(path)).toEqual([home]);
    });

    it.each([
        ['/research/news', ['nav.items.inicio', 'nav.sections.analisis', 'nav.research', 'nav.items.noticias']],
        ['/research/sources', ['nav.items.inicio', 'nav.sections.analisis', 'nav.research', 'nav.items.fuentes']],
        ['/inversores/canales', ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.knowledge', 'nav.items.canales']],
        ['/knowledge-graph', ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.knowledge', 'nav.items.grafo']],
        ['/portfolio', ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.resumen']],
        ['/portfolio/intelligence', ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.inteligencia']],
        ['/calendar/resultados', ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.calendario', 'nav.subroutes.resultados']],
        ['/calendar/suscripcion', ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.calendario', 'nav.subroutes.suscripcion']],
        ['/screener', ['nav.items.inicio', 'nav.sections.analisis', 'nav.screeners', 'nav.screener']],
        ['/discover', ['nav.items.inicio', 'nav.items.discover']],
    ])('uses declared parents and canonical labels for %s', (path, expected) => {
        expect(labels(path as string)).toEqual(expected);
    });

    it('routes a cross-hub parent to the actual library, never the URL parent', () => {
        const crumbs = buildCrumbs('/inversores/canales');
        expect(crumbs[2]).toMatchObject({ href: '/knowledge', labelKey: 'nav.items.knowledge' });
        expect(crumbs.at(-1)?.href).toBe('/inversores/canales');
        expect(crumbs.some((crumb) => crumb.href === '/inversores')).toBe(false);
    });

    it('keeps ticker casing and cumulative hrefs for unknown research children', () => {
        expect(buildCrumbs('/research/BRK.B/custom-panel')).toEqual([
            home,
            { labelKey: 'nav.sections.analisis' },
            { href: '/research', labelKey: 'nav.research' },
            { href: '/research/BRK.B', rawLabel: 'BRK.B' },
            { href: '/research/BRK.B/custom-panel', rawLabel: 'custom-panel' },
        ]);
    });

    it.each([
        ['warren-buffett', 'Warren Buffett'],
        ['berkshire', 'Berkshire'],
        ['ABC', 'ABC'],
        ['id-42', 'id-42'],
    ])('humanizes investor slug %s without changing identifiers', (slug, expected) => {
        expect(buildCrumbs(`/inversores/${slug}`).at(-1)).toEqual({ href: `/inversores/${slug}`, rawLabel: expected });
    });

    it('ignores empty trailing path segments', () => {
        expect(buildCrumbs('/research/ASTS/')).toEqual(buildCrumbs('/research/ASTS'));
    });

    it('makes every catalog route reachable without fake section links', () => {
        for (const item of flattenNavItems()) {
            const crumbs = buildCrumbs(item.href);
            expect(crumbs.at(-1)?.href, item.href).toBe(item.href);
            for (const crumb of crumbs) {
                if (crumb.href) expect(crumb.href).toMatch(/^\//);
                else expect(crumb.labelKey).toBeDefined();
            }
        }
    });

    it('preserves canonical Spanish hub names, except an already named section', () => {
        const resolve = (key: string) => key.replace(/^nav\./, '').split('.').reduce<unknown>((value, part) => {
            return value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined;
        }, navEs);
        for (const hub of NAV_SECTIONS.flatMap((section) => section.items)) {
            const crumbs = buildCrumbs(hub.href);
            const texts = crumbs.map((crumb) => crumb.labelKey ? resolve(crumb.labelKey) : crumb.rawLabel);
            expect(texts, hub.href).toContain(resolve(hub.labelKey));
        }
    });
});
