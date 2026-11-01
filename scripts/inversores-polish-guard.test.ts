/** Inversores pulido: migas legibles, "1 nueva", enlaces en fila y paginacion dentro de la pagina. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: explicit extension for node strip-types.
import { newLabel } from '../app/(root)/inversores/_components/labels.ts';
const ES_INVESTORS_JSON = readFileSync('lib/i18n/messages/es/investors.json', 'utf8');

const read = (path: string) => readFileSync(path, 'utf8');
// La jerarquia de migas vive en lib/nav/build-crumbs.ts (funcion pura); el
// componente solo presenta. La guarda mira ambos.
const crumbs = read('components/layout/Breadcrumbs.tsx') + read('lib/nav/build-crumbs.ts');
const grid = (read('app/(root)/inversores/page.tsx') + ES_INVESTORS_JSON);
const portfolios = (read('app/(root)/inversores/page.tsx') + ES_INVESTORS_JSON); // carteras fusionada en el hub (decision de Nico, 2026-10-20)
// Mas compradas es ahora una vista de /ownership (Movimientos 13F) por decision de Nico, WhatsApp 2026-10-20 00:59.
const bought = read('app/(root)/ownership/_components/MostBought.tsx');
const ficha = read('app/(root)/inversores/_components/Portfolio.tsx');
const pagination = (read('app/(root)/inversores/_components/Pagination.tsx') + readFileSync('app/(root)/inversores/_components/PaginationNav.tsx', 'utf8') + ES_INVESTORS_JSON + readFileSync('lib/i18n/messages/es/ui.json', 'utf8'));

test('las migas no muestran el slug crudo de las subpaginas de Inversores', () => {
    // Ni 'carteras' ni 'mas-compradas' tienen miga propia: ambas rutas se
    // fusionaron (Inversores y Movimientos 13F; decision de Nico, 2026-10-20).
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
    // Barra final de 4 destinos en UNA fila (decisión de Nico, WhatsApp
    // 2026-10-20 00:59 y 01:15): sin wrap, scroll horizontal si no cabe.
    assert.match(read('app/(root)/inversores/_components/HubNav.tsx'), /flex max-w-5xl flex-nowrap gap-2 overflow-x-auto/);
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
