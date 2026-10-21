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

const labels = (path: string) => buildCrumbs(path).map((crumb) => crumb.label);

void test('canales: el nivel intermedio es el hub con su nombre canónico del menú lateral', () => {
    // ROUTE_CATALOG etiqueta /knowledge como «Conocimiento» (cabecera del
    // subnav contextual); NAV_SECTIONS lo llama «Biblioteca» y ese es el
    // nombre que la miga debe mostrar para coincidir con el sidebar.
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
    assert.deepEqual(labels('/screener'), ['Inicio', 'Análisis', 'Screeners', 'Mercado']);
});

void test('regresión: /inversores a secas no se mueve', () => {
    assert.deepEqual(labels('/inversores'), ['Inicio', 'Señales', 'Inversores']);
});

void test('el menú de acciones de la ficha tiene scroll propio (10 destinos no caben en viewport bajo)', () => {
    const menu = readFileSync('components/research/CompanyActionsMenu.tsx', 'utf8');
    assert.match(menu, /overflow-y-auto/, 'sin scroll interno las últimas entradas caen fuera del viewport');
    assert.match(menu, /max-h-\[/, 'altura máxima acotada al viewport');
});
