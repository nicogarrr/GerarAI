/**
 * Guard de la paginación local de research: historial de versiones y
 * afirmaciones se cortan de 10 en 10 con controles reales, no scroll
 * infinito ni cientos de tarjetas de golpe.
 *
 * Ejecución: node --experimental-strip-types --test scripts/research-pagination-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_PAGE_SIZE,
  clampPage,
  pageCount,
  pageLabel,
  paginateItems,
  // @ts-expect-error Node strip-types exige la extensión explícita.
} from '../lib/ux/pagination.ts';

const RESEARCH_PAGE = 'app/(root)/research/[ticker]/page.tsx';
const PAGINATION = 'components/ui/pagination.tsx';
const THESIS_PAGE = 'app/(root)/research/[ticker]/tesis/page.tsx';

test('10 por página, acotado y sin páginas vacías', () => {
  assert.equal(DEFAULT_PAGE_SIZE, 10);
  assert.equal(pageCount(0), 1);
  assert.equal(pageCount(10), 1);
  assert.equal(pageCount(11), 2);

  const first = paginateItems(Array.from({ length: 25 }, (_, i) => i + 1), 1);
  assert.deepEqual(first, { page: 1, pages: 3, items: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], from: 1, to: 10 });

  const second = paginateItems(Array.from({ length: 25 }, (_, i) => i + 1), 2);
  assert.deepEqual(second.items, [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
  assert.equal(second.from, 11);
  assert.equal(second.to, 20);

  const outOfRange = paginateItems(Array.from({ length: 25 }, (_, i) => i + 1), 99);
  assert.equal(outOfRange.page, 3);
  assert.deepEqual(outOfRange.items, [21, 22, 23, 24, 25]);
  assert.deepEqual(paginateItems([], 4), { page: 1, pages: 1, items: [], from: 0, to: 0 });
  assert.equal(clampPage(Number.NaN, 3), 1);
  assert.equal(pageLabel(2, 3), 'Página 2 de 3');
});

test('la ficha pagina historial, afirmaciones y hechos financieros móviles con el componente reutilizable', () => {
  const page = readFileSync(RESEARCH_PAGE, 'utf8');
  // Los hechos financieros móviles paginan dentro de FactsPanels.
  const panels = readFileSync('components/research/FactsPanels.tsx', 'utf8');
  const src = page + '\n' + panels;
  assert.equal((src.match(/<PagedList/g) ?? []).length, 3, 'historial, afirmaciones y hechos financieros móviles usan PagedList');
  assert.match(page, /collapseVersionHistory\(data\.historyDetail\.history\)\.map/);
  assert.match(page, /groupClaimsByVersion\(data\.claims, data\.history\)\.map/);
  assert.match(page, /label=\{t\('research\.fichaVersionHistory'\)\}/);
  assert.match(panels, /label="Hechos financieros"/);
  assert.match(panels, /pageSize=\{FACTS_MOBILE_PAGE\}/);
  assert.match(panels, /FACTS_MOBILE_PAGE = 10/);
  assert.match(page, /label=\{t\('research\.fichaClaimsOf', \{ label: group\.label \}\)\}/);
  assert.equal((page.match(/pageSize=\{10\}/g) ?? []).length, 2);
});

test('el componente paginador es cliente, accesible y conserva el estado', () => {
  const component = readFileSync(PAGINATION, 'utf8');
  assert.match(component, /'use client'/);
  assert.match(component, /useState\(1\)/);
  assert.ok(component.includes("aria-label={t('ui.pagination.aria', { label })}"));
  for (const [locale, expected] of [['es', 'Paginación: {label}'], ['en', 'Pagination: {label}']]) {
    assert.equal(JSON.parse(readFileSync(`lib/i18n/messages/${locale}/ui.json`, 'utf8')).pagination.aria, expected);
  }
  assert.match(component, /aria-current="page"/);
  assert.match(component, /pageLabel\(current, pages\)/);
  assert.match(component, /onPageChange\(current - 1\)/);
  assert.match(component, /onPageChange\(current \+ 1\)/);
  assert.match(component, /<React\.Fragment key=\{item\.key\}>/);
});

test('sin tesis publicada la página conserva un H1', () => {
  const page = readFileSync(THESIS_PAGE, 'utf8');
  assert.match(page, /title=\{t\('research\.thesisDoc\.noPublishedTitle', \{ ticker \}\)\}\s+titleAs="h1"/);
});
