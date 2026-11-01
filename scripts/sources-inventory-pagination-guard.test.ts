/**
 * Guarda F131: el inventario global de fuentes mostraba los 50 documentos
 * más recientes sin forma de llegar al resto (432 en prod): sin paginación,
 * sin filtro. El backend ya pagina y filtra (?page=, ?ticker=); ahora la UI
 * lo usa con contador honesto del subconjunto filtrado.
 *
 * Los tests ejercitan el helper real (lib/research/sources-inventory.ts) y
 * comprueban que la página y la acción lo usan de verdad.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const ES_SOURCES = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).sourcesPage;
import test from 'node:test';

import {
    SOURCES_PAGE_SIZE,
    firstSearchParam,
    normalizeSourcesTicker,
    sourcesHref,
    sourcesPageInfo,
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
} from '../lib/research/sources-inventory.ts';

const PAGE = 'app/(root)/research/sources/page.tsx';
const ACTIONS = 'lib/actions/research.actions.ts';

void test('la paginación acota la página y cuenta el rango visible de verdad', () => {
    const info = sourcesPageInfo(432, 1);
    assert.deepEqual(info, { page: 1, pages: 9, from: 1, to: SOURCES_PAGE_SIZE });
    assert.deepEqual(sourcesPageInfo(432, 9).to, 432);
    assert.equal(sourcesPageInfo(432, 99).page, 9, 'página fuera de rango cae en la última, nunca en una vacía');
    assert.deepEqual(sourcesPageInfo(0, 3), { page: 1, pages: 1, from: 0, to: 0 });
});

void test('el filtro de ticker se normaliza y los enlaces lo conservan', () => {
    assert.equal(normalizeSourcesTicker(' aapl '), 'AAPL');
    assert.equal(normalizeSourcesTicker(''), '');
    assert.equal(firstSearchParam(['AAPL', 'MSFT']), 'AAPL', 'claves repetidas: primer valor');
    assert.equal(firstSearchParam(undefined), '');
    assert.equal(sourcesHref('', 1), '/research/sources');
    assert.equal(sourcesHref('aapl', 2), '/research/sources?ticker=AAPL&page=2');
    assert.equal(sourcesHref('', 3), '/research/sources?page=3');
});

void test('la acción pasa filtros y página a listado y cuenta del mismo subconjunto', () => {
    const actions = readFileSync(ACTIONS, 'utf8');
    assert.match(actions, /getResearchSources\(options: ResearchSourcesOptions = \{\}\)/, 'firma con filtros tipados');
    assert.match(actions, /filters\.set\('ticker', ticker\)/, 'el listado recibe el ticker');
    assert.match(actions, /filters\.set\('scope', options\.scope\)/, 'el alcance viaja al backend');
    assert.match(actions, /filters\.set\('source_type', sourceType\)/, 'el tipo de fuente viaja al backend');
    assert.match(actions, /filters\.set\('q', q\)/, 'la búsqueda viaja al backend');
    assert.match(actions, /params\.set\('page', String\(effectivePage\)\)/, 'el listado recibe la página acotada');
    assert.match(actions, /documents\/count\$\{countQuery\}/, 'la cuenta recibe el mismo filtro');
    assert.match(actions, /sourcesPageInfo\(documentsTotal, requested\)/, 'la página se acota con el total real');
});

void test('la página declara el subconjunto filtrado y pagina con enlaces', () => {
    const page = readFileSync(PAGE, 'utf8');
    assert.match(page, /searchParams\?: Promise<\{[\s\S]*ticker\?: string \| string\[\];[\s\S]*page\?: string \| string\[\];[\s\S]*scope\?: string \| string\[\];[\s\S]*source_type\?: string \| string\[\];[\s\S]*q\?: string \| string\[\];/, 'searchParams tipado con arrays y filtros');
    assert.match(page, /firstSearchParam\(params\.ticker\)/, 'ticker normalizado');
    assert.match(page, /<form action="\/research\/sources"[^>]*method="get">/, 'filtro por GET');
    assert.match(page, /htmlFor="sources-ticker"/, 'label accesible');
    assert.match(page, /t\('research\.sourcesPage\.docsOfTicker', \{[\s\S]{0,120}?ticker \}\)/, 'el contador nombra el filtro');
    assert.match(ES_SOURCES.docsOfTicker, /documentos de \{ticker\}/, 'el contador nombra el filtro (es)');
    assert.match(page, /sourcesHref\(ticker, pageInfo\.page [+-] 1, filters\)/, 'paginación conserva todos los filtros');
    assert.match(page, /t\('research\.sourcesPage\.emptyTicker', \{ ticker \}\)/, 'filtro sin resultados lo dice y no finge inventario vacío');
    assert.equal(ES_SOURCES.emptyTicker, 'Sin documentos de {ticker}.');
    assert.match(page, /t\('research\.sourcesPage\.removeTickerFilter'\)/, 'salida explícita del filtro');
    assert.match(ES_SOURCES.removeTickerFilter, /Quitar (el )?filtro/, 'salida explícita del filtro (es)');
    assert.match(page, /t\('research\.sourcesPage\.auditsCount'[\s\S]{0,120}?\}\)\}\{ticker \? ' \(global\)' : ''\}/, 'el contador de auditorías declara que es global bajo filtro');
});
