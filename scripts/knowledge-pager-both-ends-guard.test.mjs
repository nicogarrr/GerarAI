import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const navs = (parameter) => page.match(new RegExp(`<PageNavigation[^>]*parameter="${parameter}"`, 'g')) ?? [];

test('documentos de la Biblioteca: paginador arriba y abajo', () => {
  assert.equal(navs('documentOffset').length, 2);
});

test('principios: paginador arriba y abajo', () => {
  assert.equal(navs('principleOffset').length, 2);
});

test('el tamano de pagina es una sola constante y no hay 50 sueltos en el paginador', () => {
  assert.match(page, /const KNOWLEDGE_PAGE_SIZE = 50;/);
  const nav = page.slice(page.indexOf('function PageNavigation'));
  assert.doesNotMatch(nav, /\b50\b/);
});

test('una sola pagina no pinta paginador', () => {
  const nav = page.slice(page.indexOf('function PageNavigation'));
  assert.match(nav, /offset === 0 && offset \+ count >= total/);
});
