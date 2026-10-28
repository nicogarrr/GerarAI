/**
 * Migas coherentes con el hub del catálogo (QA cohesión 2026-10-21):
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

const labels = (path: string) => buildCrumbs(path).map((crumb) => crumb.label);

void test('canales: el nivel intermedio es el hub con su nombre canónico del menú lateral', () => {
    // /knowledge se llama «Biblioteca» en NAV_SECTIONS, ROUTE_CATALOG y H1.
    assert.deepEqual(labels('/inversores/canales'), ['Inicio', 'Análisis', 'Biblioteca', 'Canales']);
    const crumbs = buildCrumbs('/inversores/canales');
    assert.equal(crumbs[2].href, '/knowledge', 'Biblioteca enlaza a su ruta real');
    assert.equal(crumbs[3].href, '/inversores/canales');
});

void test('regresión: sub-página de ficha mantiene cadena y etiqueta propia', () => {
    assert.deepEqual(labels('/research/ASTS/tesis'), ['Inicio', 'Análisis', 'Research', 'ASTS', 'Tesis']);
});

void test('regresión: pestaña de calendario mantiene cadena y etiqueta propia', () => {
    assert.deepEqual(labels('/calendar/resultados'), ['Inicio', 'Cartera', 'Calendario', 'Resultados']);
});

void test('regresión: hijo declarado del mismo hub conserva a su padre por URL', () => {
    assert.deepEqual(labels('/research/news'), ['Inicio', 'Análisis', 'Research', 'Noticias']);
    assert.deepEqual(labels('/screener'), ['Inicio', 'Análisis', 'Screeners', 'Explorar acciones']);
});

void test('regresión: /inversores a secas no se mueve', () => {
    assert.deepEqual(labels('/inversores'), ['Inicio', 'Señales', 'Inversores']);
});

void test('el menú de acciones de la ficha tiene scroll propio (10 destinos no caben en viewport bajo)', () => {
    const menu = readFileSync('components/research/CompanyActionsMenu.tsx', 'utf8');
    assert.match(menu, /overflow-y-auto/, 'sin scroll interno las últimas entradas caen fuera del viewport');
    assert.match(menu, /max-h-\[/, 'altura máxima acotada al viewport');
});

void test('el hub /knowledge se nombra Biblioteca también en su propia ruta', () => {
    assert.deepEqual(labels('/knowledge'), ['Inicio', 'Análisis', 'Biblioteca']);
    assert.deepEqual(labels('/knowledge-graph'), ['Inicio', 'Análisis', 'Biblioteca', 'Grafo']);
});

void test('dedupe: /portfolio no repite Cartera cuando la sección ya lo dice', () => {
    assert.deepEqual(labels('/portfolio'), ['Inicio', 'Cartera', 'Resumen']);
});

void test('una etiqueta por ruta: Mercados, Cuenta demo y Biblioteca', () => {
    assert.deepEqual(labels('/mercados'), ['Inicio', 'Análisis', 'Panorama de mercado']);
    assert.deepEqual(labels('/paper-trading'), ['Inicio', 'Cartera', 'Mi cuenta demo']);
    assert.deepEqual(labels('/knowledge'), ['Inicio', 'Análisis', 'Biblioteca']);
});

void test('ningún hub muestra un nombre divergente del canónico del menú lateral', () => {
    for (const hub of NAV_SECTIONS.flatMap((section) => section.items)) {
        if (hub.href === '/inicio') continue;
        const crumbs = buildCrumbs(hub.href);
        const last = crumbs[crumbs.length - 1];
        const section = crumbs.length > 2 ? crumbs[crumbs.length - 2].label : undefined;
        // Etiqueta de catálogo distinta solo vale cuando el nombre canónico
        // ya lo ocupa el nivel de sección (/portfolio -> Cartera > Resumen).
        assert.ok(
            last.label === hub.label || section === hub.label,
            `${hub.href}: miga «${last.label}» diverge del nombre canónico «${hub.label}» del menú lateral`,
        );
    }
});
