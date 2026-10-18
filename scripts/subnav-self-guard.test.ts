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
    assert.match(constants, /href: '\/portfolio', label: 'Resumen', icon: Briefcase, hub: '\/portfolio', subnavHideSelf: true/);
    const catalog = constants.slice(constants.indexOf('export const ROUTE_CATALOG'));
    const knowledge = catalog.slice(catalog.indexOf("href: '/knowledge',"), catalog.indexOf("href: '/knowledge',") + 400);
    assert.match(knowledge, /subnavHideSelf: true/);
    const research = catalog.slice(catalog.indexOf("href: '/research',"), catalog.indexOf("href: '/research',") + 400);
    assert.doesNotMatch(research, /subnavHideSelf/);
});
