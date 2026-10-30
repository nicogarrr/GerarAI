/** Subnav contextual: la página que ya navega a sí misma (pestaña «Resumen»
 *  en /portfolio, encabezado «Conocimiento» en /knowledge) no repite ese
 *  enlace en el subnav de la sección (duplicado QA). El resto de páginas
 *  conserva su enlace, como «Empresas» en /research. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const nav = readFileSync('components/layout/SectionNav.tsx', 'utf8');
const constants = readFileSync('lib/constants.ts', 'utf8');

test('el filtro del subnav oculta el self-link solo cuando el item lo pide', () => {
    assert.match(nav, /item\.href===pathname&&item\.subnavHideSelf/);
    assert.match(constants, /subnavHideSelf\?: boolean;/);
});

test('/portfolio y /knowledge ocultan su self-link; /research conserva el suyo', () => {
    assert.match(constants, /href: '\/portfolio', labelKey: 'nav.items.resumen', icon: Briefcase, hub: '\/portfolio', subnavHideSelf: true/);
    const catalog = constants.slice(constants.indexOf('export const ROUTE_CATALOG'));
    const knowledge = catalog.slice(catalog.indexOf("href: '/knowledge',"), catalog.indexOf("href: '/knowledge',") + 400);
    assert.match(knowledge, /subnavHideSelf: true/);
    const research = catalog.slice(catalog.indexOf("href: '/research',"), catalog.indexOf("href: '/research',") + 400);
    assert.doesNotMatch(research, /subnavHideSelf/);
});

test('la subnav anuncia el overflow horizontal con la pista del patron y conserva accesibilidad', () => {
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/shell.json', 'utf8')).sectionNav.scrollHint, 'Desliza para ver más secciones');
    assert.match(nav, /OverflowScrollRegion/, 'reutiliza la region con pista');
    assert.match(nav, /hint=\{t\('shell.sectionNav.scrollHint'\)\}/, 'pista con texto de secciones');
    assert.match(nav, /aria-controls="subnav-seccion-lista"/, 'toggle sigue controlando la lista');
    assert.match(nav, /aria-expanded=\{open\}/, 'toggle sigue exponiendo estado');
    assert.match(nav, /sm:flex-wrap/, 'en escritorio la lista sigue envolviendo (sin scroll)');
});

test('la pista del componente es parametrizable sin romper el texto de tablas', () => {
    const region = readFileSync('components/ui/overflow-scroll-region.tsx', 'utf8');
    assert.match(region, /hint\?: string/, 'prop hint opcional');
    assert.ok(region.includes("hint ?? t('ui.scrollRegion.hintColumns')"), 'default traducido intacto para tablas');
    assert.match(region, /\{resolvedHint\}/);
    for (const [locale, expected] of [['es', 'Desliza para ver más columnas'], ['en', 'Scroll to see more columns']]) {
        assert.equal(JSON.parse(readFileSync(`lib/i18n/messages/${locale}/ui.json`, 'utf8')).scrollRegion.hintColumns, expected);
    }
});
