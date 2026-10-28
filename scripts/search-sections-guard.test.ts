import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { navItemMatchesSearch, navSectionMatchesSearch, normalizeNavSearchTerm } from '../lib/search/nav-search.ts';

const icon = (() => null) as never;

const carteraSection = {
    title: 'Cartera',
    items: [
        { href: '/portfolio', label: 'Resumen', icon, hub: '/portfolio' },
        { href: '/portfolio/intelligence', label: 'Inteligencia', icon, hub: '/portfolio' },
        { href: '/risk', label: 'Exposiciones', icon, hub: '/portfolio' },
        { href: '/taxes', label: 'Impuestos', icon, hub: '/portfolio' },
    ],
};

const flatten = (sections: { items: unknown[] }[]) =>
    sections.flatMap((section) => section.items.flatMap((raw) => { const item = raw as { children?: unknown[] }; return item.children ? [item, ...item.children] : [item]; })) as never[];

test('escribir el nombre de la sección («cartera») encuentra su grupo', () => {
    // QA prod 19 oct: "cartera" devolvía "Sin resultados" aunque Cartera es un
    // destino del menú principal; solo se miraba item.label.
    assert.equal(navSectionMatchesSearch(carteraSection, 'cartera', flatten), true);
    const visibles = flatten([carteraSection]).filter((item) => navItemMatchesSearch(carteraSection, item, 'cartera'));
    assert.ok(visibles.length > 0, 'el grupo Cartera debe ofrecer destinos al buscar «cartera»');
});

test('la etiqueta del destino y la descripción también casan, sin tildes', () => {
    assert.equal(navItemMatchesSearch(carteraSection, carteraSection.items[3], 'impuestos'), true);
    assert.equal(navItemMatchesSearch(carteraSection, carteraSection.items[2], 'exposicion'), true);
    assert.equal(normalizeNavSearchTerm('Inversión'), 'inversion');
    assert.equal(navItemMatchesSearch(carteraSection, carteraSection.items[0], 'xyzq'), false);
});

test('SearchCommand usa el matcher de secciones en vez de filtrar solo por label', () => {
    const view = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
    assert.match(view, /navSectionMatchesSearch\(section, searchTerm, flattenNavItems\)/);
    assert.match(view, /navItemMatchesSearch\(section, item, searchTerm\)/);
    assert.doesNotMatch(view, /item\.label\.toLocaleLowerCase\(\)\.includes/);
});

test('el catálogo sigue teniendo una sección Cartera navegable', () => {
    const constants = readFileSync('lib/constants.ts', 'utf8');
    assert.match(constants, /title: 'Cartera'/);
    assert.match(constants, /href: '\/portfolio'/);
});
