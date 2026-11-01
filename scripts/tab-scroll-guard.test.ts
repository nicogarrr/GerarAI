import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard: cambiar de pestaña no puede devolver al usuario al inicio de la
 * página. Las pestañas de la ficha (/research/[ticker]?view=) y de la
 * biblioteca (/knowledge?tab=) son enlaces a la MISMA página con otro query
 * param; un <Link> sin `scroll={false}` hace scroll arriba y la transición
 * se percibe como un refresco (bug reportado por Nico, 2026-10-19).
 *
 * E2E que mide el salto en px: e2e/tab-scroll-preservation.spec.ts.
 */

function navBlock(src: string, ariaLabelStart: string): string {
    const labelAt = src.indexOf(ariaLabelStart);
    assert.ok(labelAt > 0, `nav "${ariaLabelStart}" existe`);
    const start = src.lastIndexOf('<nav', labelAt);
    assert.ok(start >= 0 && start < labelAt, `nav "${ariaLabelStart}" abre antes de la etiqueta`);
    const end = src.indexOf('</nav>', labelAt);
    assert.ok(end > labelAt, `nav "${ariaLabelStart}" se cierra`);
    return src.slice(start, end);
}

describe('pestañas con estado en la URL conservan el scroll', () => {
    it('ficha: la fila de seis pestañas no resetea el scroll', () => {
        const page = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
        const nav = navBlock(page, "aria-label={t('research.companyNav.aria')}");
        // Las seis pestañas son la MISMA ruta con otro ?view= (una fila,
        // 29-oct-2026): todas llevan scroll={false}.
        assert.ok(nav.includes('scroll={false}'), 'las pestañas llevan scroll={false}');
        assert.ok(nav.includes('TABS.map'), 'una sola fila alimentada por TABS');
        assert.ok(!nav.includes('Módulos de'), 'sin fila de módulos: son secciones ancladas');
    });
    it('biblioteca: las pestañas y los filtros de principios no resetean el scroll', () => {
        const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
        const tabLink = '<Link href={key === TABS.biblioteca ? \'/knowledge\' : `/knowledge?tab=${key}`} scroll={false}>';
        assert.ok(page.includes(tabLink), 'pestañas de /knowledge con scroll={false}');
        const filterLink = "<Link href={status ? `/knowledge?tab=principios&status=${status}` : '/knowledge?tab=principios'} scroll={false}>";
        assert.ok(page.includes(filterLink), 'filtros de principios con scroll={false}');
    });
});
