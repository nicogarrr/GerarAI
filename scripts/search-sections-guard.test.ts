import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { navItemMatchesSearch, navSectionMatchesSearch, normalizeNavSearchTerm } from '../lib/search/nav-search.ts';

// Tras la i18n el matcher recibe los textos YA RESUELTOS al locale activo
// (las claves nav.* viven en lib/constants.ts y las traduce el componente).
const carteraHaystacks = [
    ['Cartera', 'Resumen'],
    ['Cartera', 'Inteligencia'],
    ['Cartera', 'Exposiciones'],
    ['Cartera', 'Impuestos'],
];

test('escribir el nombre de la sección («cartera») encuentra su grupo', () => {
    // QA prod 19 oct: "cartera" devolvía "Sin resultados" aunque Cartera es un
    // destino del menú principal; solo se miraba la etiqueta del destino.
    assert.equal(navSectionMatchesSearch(carteraHaystacks, 'cartera'), true);
    const visibles = carteraHaystacks.filter((haystacks) => navItemMatchesSearch(haystacks, 'cartera'));
    assert.ok(visibles.length > 0, 'el grupo Cartera debe ofrecer destinos al buscar «cartera»');
});

test('la etiqueta del destino y la descripción también casan, sin tildes', () => {
    assert.equal(navItemMatchesSearch(carteraHaystacks[3], 'impuestos'), true);
    assert.equal(navItemMatchesSearch(carteraHaystacks[2], 'exposicion'), true);
    assert.equal(normalizeNavSearchTerm('Inversión'), 'inversion');
    assert.equal(navItemMatchesSearch(carteraHaystacks[0], 'xyzq'), false);
});

test('SearchCommand usa el matcher de secciones con textos resueltos por t()', () => {
    const view = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
    assert.match(view, /navSectionMatchesSearch\(resolvedItems\.map/);
    assert.match(view, /navItemMatchesSearch\(haystacks, searchTerm\)/);
    assert.doesNotMatch(view, /item\.label\.toLocaleLowerCase\(\)\.includes/);
});

test('el catálogo sigue teniendo una sección Cartera navegable', () => {
    const constants = readFileSync('lib/constants.ts', 'utf8');
    assert.match(constants, /titleKey: 'nav\.sections\.cartera'/);
    assert.match(constants, /href: '\/portfolio'/);
});
