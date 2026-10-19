/** Inversores pulido: migas legibles, "1 nueva", enlaces en fila y paginacion dentro de la pagina. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: explicit extension for node strip-types.
import { newLabel } from '../app/(root)/inversores/_components/labels.ts';

const read = (path: string) => readFileSync(path, 'utf8');
const crumbs = read('components/layout/Breadcrumbs.tsx');
const grid = read('app/(root)/inversores/page.tsx');
const portfolios = read('app/(root)/inversores/page.tsx'); // carteras fusionada en el hub (decision de Nico, 2026-10-20)
const bought = read('app/(root)/inversores/mas-compradas/page.tsx');
const ficha = read('app/(root)/inversores/_components/Portfolio.tsx');
const pagination = read('app/(root)/inversores/_components/Pagination.tsx');

test('las migas no muestran el slug crudo de las subpaginas de Inversores', () => {
    assert.match(crumbs, /'mas-compradas': 'Más compradas'/);
    assert.match(crumbs, /humanizeSlug/);
});

test('singular "1 nueva" y plural "2 nuevas" (comportamiento real, no regex)', () => {
    assert.equal(newLabel(1), '1 nueva');
    assert.equal(newLabel(2), '2 nuevas');
    assert.equal(newLabel(12), '12 nuevas');
});

test('la página de Más compradas usa newLabel dentro de la plantilla (sin llaves literales)', () => {
    assert.match(bought, /\$\{newLabel\(item\.new_count\)\}/);
    assert.ok(!/\{item\.new_count === 1/.test(bought));
});

test('los enlaces de la cabecera van en una fila', () => {
    assert.match(read('app/(root)/inversores/_components/HubNav.tsx'), /flex max-w-5xl flex-wrap gap-2/);
});

test('rejilla, carteras y ficha paginan dentro de la pagina, sin scroll infinito', () => {
    for (const source of [grid, portfolios, ficha]) {
        assert.match(source, /paginate\(/);
        assert.match(source, /<Pagination/);
    }
    assert.match(pagination, /Página \{page\} de \{total\}/);
    assert.ok(!/IntersectionObserver|infinite/i.test(pagination + grid + portfolios));
});

test('la ficha conserva la vista al cambiar de pagina', () => {
    assert.match(ficha, /params=\{\{ vista: view \}\}/);
    assert.match(ficha, /view === ["']cambios["']/);
});
