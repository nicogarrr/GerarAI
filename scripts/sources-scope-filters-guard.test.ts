/**
 * Guard de los filtros de Fuentes: alcance («Mi universo» por defecto /
 * «Todas»), tipo de fuente y búsqueda. El backend los añade en paralelo;
 * la UI no puede ignorarlos ni perderlos al paginar.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_SOURCES_SCOPE,
  normalizeSourcesQuery,
  normalizeSourcesScope,
  normalizeSourcesType,
  sourcesHref,
  // @ts-expect-error Node strip-types exige la extensión explícita.
} from '../lib/research/sources-inventory.ts';

const PAGE = 'app/(root)/research/sources/page.tsx';
const ACTIONS = 'lib/actions/research.actions.ts';

test('«Mi universo» es el alcance por defecto y «Todas» una elección explícita', () => {
  assert.equal(DEFAULT_SOURCES_SCOPE, 'universe');
  assert.equal(normalizeSourcesScope(''), 'universe');
  assert.equal(normalizeSourcesScope('universe'), 'universe');
  assert.equal(normalizeSourcesScope('ALL'), 'all');
  assert.equal(normalizeSourcesType(' SEC '), 'sec');
  assert.equal(normalizeSourcesType('<script>'), 'script');
  assert.equal(normalizeSourcesQuery('  informe   anual  '), 'informe anual');
});

test('los enlaces conservan alcance, tipo, búsqueda y ticker al paginar', () => {
  assert.equal(
    sourcesHref('aapl', 2, { scope: 'all', sourceType: 'sec', q: '10-K' }),
    '/research/sources?ticker=AAPL&scope=all&source_type=sec&q=10-K&page=2',
  );
  assert.equal(
    sourcesHref('', 1, { scope: 'universe' }),
    '/research/sources?scope=universe',
  );
});

test('la página expone los tres controles y un vacío honesto que lleva a «Todas»', () => {
  const page = readFileSync(PAGE, 'utf8');
  assert.match(page, /name="scope"/);
  assert.match(page, /<option value="universe">Mi universo<\/option>/);
  assert.match(page, /<option value="all">Todas<\/option>/);
  assert.match(page, /name="source_type"/);
  assert.match(page, /name="q"/);
  assert.match(page, /Sin documentos en tu universo\./);
  assert.match(page, /Cambia el alcance a «Todas» para ver el inventario completo\./);
  assert.match(page, /href=\{sourcesHref\(ticker, 1, \{ scope: 'all', sourceType: sourceType \|\| undefined, q: query \|\| undefined \}\)\}/);
});

test('la acción envía scope, source_type y q a ambos endpoints', () => {
  const actions = readFileSync(ACTIONS, 'utf8');
  assert.match(actions, /filters\.set\('scope', options\.scope\)/);
  assert.match(actions, /filters\.set\('source_type', options\.sourceType\)/);
  assert.match(actions, /filters\.set\('q', query\)/);
  assert.match(actions, /const countQuery = filters\.size \? `\?\$\{filters\.toString\(\)\}` : ''/);
  assert.match(actions, /const params = new URLSearchParams\(filters\)/);
});
