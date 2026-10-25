import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const sidebar = readFileSync('components/layout/Sidebar.tsx', 'utf8');
const navItems = readFileSync('components/NavItems.tsx', 'utf8');

test('F283: el padre con la página actual en un hijo ya no recibe el estilo activo', () => {
    // Antes: linkClasses(branchActive) / classes(branchActive) pintaban el
    // padre («Screeners») con fondo + barra teal a la vez que el hijo
    // («Vista de mercado») llevaba aria-current + activo: doble resaltado.
    assert.match(sidebar, /linkClasses\(active, collapsed, 'text-sm', branchActive\)/);
    assert.match(navItems, /classes\(active, 'text-base', branchActive\)/);
    assert.doesNotMatch(sidebar, /linkClasses\(branchActive/);
    assert.doesNotMatch(navItems, /classes\(branchActive\)/);
});

test('F283: el estado rama es texto claro sin fondo ni barra', () => {
    for (const src of [sidebar, navItems]) {
        assert.match(src, /: branch\n/);
        assert.match(src, /\? 'text-gray-100 hover:bg-gray-800/);
    }
});

test('F283: aria-current solo es «page» en el destino exacto; el hub es «true»', () => {
    for (const src of [sidebar, navItems]) {
        assert.match(src, /isNavItemExact/, 'el menu distingue coincidencia exacta de hub');
        assert.match(src, /ariaCurrent\(active, isNavItemExact\(pathname, item\.href\)\)/, 'el item usa page/true');
    }
    assert.match(sidebar, /return exact \? 'page' : 'true'/, 'el hub activo no se publica como pagina');
});
