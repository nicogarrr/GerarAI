/**
 * Migas coherentes con el hub del catálogo (QA cohesión 2026-10-21).
 * Tras la i18n las migas llevan CLAVES nav.* (las resuelve el componente):
 * este guard compara claves, no literales.
 * un hijo que cuelga por URL de una sección pero pertenece a OTRO hub
 * (/inversores/canales -> hub Biblioteca) no puede mostrar la cadena del
 * padre por URL ("Señales > Inversores") mientras sidebar y subnav dicen
 * Biblioteca/Conocimiento. Regresiones: Tesis, Resultados y la cadena
 * padre-hijo normal (/research/news) no se mueven.
 * Ejecución: node --experimental-strip-types --test scripts/breadcrumbs-hub-crossing-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { buildCrumbs } from '../lib/nav/build-crumbs.ts';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { NAV_SECTIONS } from '../lib/constants.ts';

const labels = (path: string) => buildCrumbs(path).map((crumb) => crumb.labelKey ?? crumb.rawLabel);

void test('canales: el nivel intermedio es el hub con su nombre canónico del menú lateral', () => {
    // /knowledge se llama «Biblioteca» en NAV_SECTIONS, ROUTE_CATALOG y H1.
    assert.deepEqual(labels('/inversores/canales'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.knowledge', 'nav.items.canales']);
    const crumbs = buildCrumbs('/inversores/canales');
    assert.equal(crumbs[2].href, '/knowledge', 'Biblioteca enlaza a su ruta real');
    assert.equal(crumbs[3].href, '/inversores/canales');
});

void test('regresión: sub-página de ficha mantiene cadena y etiqueta propia', () => {
    assert.deepEqual(labels('/research/ASTS/tesis'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.research', 'ASTS', 'nav.subroutes.tesis']);
});

void test('regresión: pestaña de calendario mantiene cadena y etiqueta propia', () => {
    assert.deepEqual(labels('/calendar/resultados'), ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.calendario', 'nav.subroutes.resultados']);
});

void test('regresión: hijo declarado del mismo hub conserva a su padre por URL', () => {
    assert.deepEqual(labels('/research/news'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.research', 'nav.items.noticias']);
    assert.deepEqual(labels('/screener'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.screeners', 'nav.screener']);
});

void test('regresión: /inversores a secas no se mueve', () => {
    assert.deepEqual(labels('/inversores'), ['nav.items.inicio', 'nav.sections.senales', 'nav.items.inversores']);
});

void test('el menú de acciones de la ficha tiene scroll propio (10 destinos no caben en viewport bajo)', () => {
    const menu = readFileSync('components/research/CompanyActionsMenu.tsx', 'utf8');
    assert.match(menu, /overflow-y-auto/, 'sin scroll interno las últimas entradas caen fuera del viewport');
    assert.match(menu, /max-h-\[/, 'altura máxima acotada al viewport');
});

void test('el hub /knowledge se nombra Biblioteca también en su propia ruta', () => {
    assert.deepEqual(labels('/knowledge'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.knowledge']);
    assert.deepEqual(labels('/knowledge-graph'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.knowledge', 'nav.items.grafo']);
});

void test('dedupe: /portfolio no repite Cartera cuando la sección ya lo dice', () => {
    assert.deepEqual(labels('/portfolio'), ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.resumen']);
});

void test('una etiqueta por ruta: Mercados, Cuenta demo y Biblioteca', () => {
    assert.deepEqual(labels('/mercados'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.panoramaMercado']);
    assert.deepEqual(labels('/paper-trading'), ['nav.items.inicio', 'nav.sections.cartera', 'nav.items.cuentaDemo']);
    assert.deepEqual(labels('/knowledge'), ['nav.items.inicio', 'nav.sections.analisis', 'nav.items.knowledge']);
});

void test('ningún hub muestra un nombre divergente del canónico del menú lateral', () => {
    // La comparacion es de TEXTO RESUELTO (es): la equivalencia titulo de
    // seccion / nombre canonico del hub la dan los valores, no las claves.
    const navEs = JSON.parse(readFileSync('lib/i18n/messages/es/nav.json', 'utf8')) as Record<string, unknown>;
    const resolveNav = (key: string): string =>
        key.replace(/^nav\./, '').split('.').reduce<unknown>((node, part) =>
            node !== null && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined, navEs) as string;
    for (const hub of NAV_SECTIONS.flatMap((section) => section.items)) {
        if (hub.href === '/inicio') continue;
        const crumbs = buildCrumbs(hub.href);
        const last = crumbs[crumbs.length - 1];
        const lastText = last.labelKey ? resolveNav(last.labelKey) : last.rawLabel;
        const section = crumbs.length > 2 ? crumbs[crumbs.length - 2].labelKey : undefined;
        const sectionText = section ? resolveNav(section) : undefined;
        const hubText = resolveNav(hub.labelKey);
        // Etiqueta de catálogo distinta solo vale cuando el nombre canónico
        // ya lo ocupa el nivel de sección (/portfolio -> Cartera > Resumen).
        assert.ok(
            lastText === hubText || sectionText === hubText,
            `${hub.href}: miga «${lastText}» diverge del nombre canónico «${hubText}» del menú lateral`,
        );
    }
});
