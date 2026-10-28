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
    it('ficha: los 3 pasos (Entender/Valorar/Seguir) no resetean el scroll', () => {
        const page = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
        const nav = navBlock(page, 'aria-label="Secciones de la empresa"');
        assert.ok(nav.includes('scroll={false}'), 'los pasos llevan scroll={false}');
    });
    it('ficha: los módulos ?view= no resetean el scroll; las subrutas sí arrancan arriba', () => {
        const page = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
        navBlock(page, 'aria-label={`Módulos de ');
        // Los enlaces de módulo salen del helper link(), fuera del bloque <nav>.
        // scroll={'path' in item}: los módulos con subruta propia (`path`)
        // navegan a OTRA página y arrancan arriba; los ?view= son la MISMA
        // página con otro query param y conservan la posición. La expresión
        // negada (!('path' in item)) hacía justo lo contrario (auditoría
        // v1.0, 2026-10-27): la pestaña subía al inicio y la subruta se
        // quedaba a media página.
        assert.ok(
            page.includes("scroll={'path' in item}"),
            'los módulos ?view= conservan el scroll y las subrutas navegan arriba',
        );
        assert.ok(
            !page.includes("scroll={!('path' in item)}"),
            'la negación invierte el comportamiento: prohibida',
        );
    });
    it('biblioteca: las pestañas y los filtros de principios no resetean el scroll', () => {
        const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
        const tabLink = '<Link href={key === TABS.biblioteca ? \'/knowledge\' : `/knowledge?tab=${key}`} scroll={false}>';
        assert.ok(page.includes(tabLink), 'pestañas de /knowledge con scroll={false}');
        const filterLink = "<Link href={status ? `/knowledge?tab=principios&status=${status}` : '/knowledge?tab=principios'} scroll={false}>";
        assert.ok(page.includes(filterLink), 'filtros de principios con scroll={false}');
    });
});
