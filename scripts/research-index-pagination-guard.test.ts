/**
 * Guarda F308: el índice de research pintaba las ~2115 empresas del registro
 * en una sola página, sin filtro ni paginación (HTML enorme y todo el detalle
 * por encima del tope salía «pendiente»). Ahora filtra (?q=) y pagina
 * (?page=) en servidor, con contador honesto de lo visible.
 *
 * Los tests ejercitan el helper real (lib/research/index-filter.ts) y
 * comprueban que la página lo usa de verdad, no solo que contiene strings.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    filterResearchIndex,
    firstSearchParam,
    paginateResearchIndex,
    parseIndexPage,
    RESEARCH_INDEX_PAGE_SIZE,
    researchIndexHref,
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
} from '../lib/research/index-filter.ts';

const PAGE = 'app/(root)/research/page.tsx';

function readSource(path: string): string {
    return readFileSync(path, 'utf8');
}

void test('el filtro encuentra por ticker o nombre sin distinguir mayúsculas', () => {
    const items = [
        { ticker: 'AAPL', name: 'Apple Inc.' },
        { ticker: 'MSFT', name: 'Microsoft Corporation' },
        { ticker: 'ITX.MC', name: 'Industria de Diseño Textil, S.A.' },
    ];
    assert.deepEqual(filterResearchIndex(items, 'apple').map((i) => i.ticker), ['AAPL']);
    assert.deepEqual(filterResearchIndex(items, 'mc').map((i) => i.ticker), ['ITX.MC']);
    assert.deepEqual(filterResearchIndex(items, '  ').length, 3, 'filtro vacío no filtra');
    assert.deepEqual(filterResearchIndex(items, 'zzz'), [], 'sin coincidencias da lista vacía');
});

void test('la paginación acota la página y cuenta lo visible de verdad', () => {
    const items = Array.from({ length: 95 }, (_, i) => ({ ticker: `T${i}`, name: `Empresa ${i}` }));
    const first = paginateResearchIndex(items, 1);
    assert.equal(first.rows.length, RESEARCH_INDEX_PAGE_SIZE);
    assert.deepEqual([first.from, first.to, first.total, first.pages], [1, RESEARCH_INDEX_PAGE_SIZE, 95, 3]);
    const last = paginateResearchIndex(items, 3);
    assert.equal(last.rows.length, 95 - 2 * RESEARCH_INDEX_PAGE_SIZE);
    assert.equal(last.to, 95);
    const outOfRange = paginateResearchIndex(items, 99);
    assert.equal(outOfRange.page, 3, 'una página fuera de rango cae en la última, nunca en una página vacía');
    assert.equal(outOfRange.rows.length, last.rows.length);
    const empty = paginateResearchIndex([], 4);
    assert.deepEqual([empty.from, empty.to, empty.pages, empty.rows.length], [0, 0, 1, 0]);
});

void test('parseIndexPage y los enlaces conservan el filtro sin inventar parámetros', () => {
    assert.equal(parseIndexPage('2'), 2);
    assert.equal(parseIndexPage('0'), 1);
    assert.equal(parseIndexPage('-3'), 1);
    assert.equal(parseIndexPage('abc'), 1);
    assert.equal(parseIndexPage(undefined), 1);
    assert.equal(researchIndexHref('', 1), '/research');
    assert.equal(researchIndexHref('apple', 1), '/research?q=apple');
    assert.equal(researchIndexHref('apple', 3), '/research?q=apple&page=3');
    assert.equal(researchIndexHref('', 2), '/research?page=2');
});

void test('claves repetidas (?q=A&q=B) se normalizan y no rompen la página', () => {
    assert.equal(firstSearchParam(['AAPL', 'MSFT']), 'AAPL', 'array: primer valor, como el navegador');
    assert.equal(firstSearchParam('AAPL'), 'AAPL');
    assert.equal(firstSearchParam(undefined), '');
    assert.equal(firstSearchParam([]), '');
    const page = readSource(PAGE);
    assert.match(page, /q\?: string \| string\[\]/, 'q se tipa como string | string[]');
    assert.match(page, /page\?: string \| string\[\]/, 'page se tipa como string | string[]');
    assert.match(page, /firstSearchParam\(params\.q\)\.trim\(\)/, 'q se normaliza antes de trim');
    assert.match(page, /parseIndexPage\(firstSearchParam\(params\.page\)\)/, 'page se normaliza antes de parsear');
});

void test('la página usa el helper y declara el contador honesto de lo visible', () => {
    const page = readSource(PAGE);
    assert.match(page, /filterResearchIndex\(ordered, query\)/, 'filtra en servidor con el helper');
    assert.match(page, /paginateResearchIndex\(filtered, requestedPage\)/, 'pagina en servidor con el helper');
    // Quick win UX 6: el bucket «tesis» del orden sale de UNA query
    // DISTINCT del backend (thesis-tickers); los snapshots (rating/fecha
    // de las tarjetas) se piden SOLO para la página visible, en lotes del
    // tope del endpoint y con el fallo de un lote aislado del resto.
    assert.match(page, /SNAPSHOT_BATCH_SIZE = 50/, 'lotes del tope del endpoint de snapshots');
    assert.match(page, /fetchInBatches\(\s*sliceTickers,/, 'snapshots solo de la página visible');
    assert.match(page, /part === null/, 'un lote fallido no borra los demás');
    assert.ok(!page.includes('THESIS_DETAIL_LIMIT'), 'ya no hay recorte de detalle por página');
    assert.ok(!page.includes('pendiente'), 'desaparece el estado «pendiente»: ninguna tarjeta visible sale sin detalle por recorte');
    // Los textos van por t(); el ES verbatim historico se fija contra el dict.
    const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
    assert.match(page, /t\('research\.showingAll', \{ from: formatNumber\(slice\.from\), to: formatNumber\(slice\.to\), total: formatNumber\(slice\.total\) \}\)/, 'contador de lo visible');
    assert.equal(es.showingAll, 'Mostrando {from}-{to} de {total} empresas');
    assert.match(page, /t\('research\.showingMatches', \{ from: formatNumber\(slice\.from\), to: formatNumber\(slice\.to\), total: formatNumber\(slice\.total\), query, companies: formatNumber\(ordered\.length\) \}\)/, 'bajo filtro también se declara el rango visible contra el total real');
    assert.equal(es.showingMatches, 'Mostrando {from}-{to} de {total} coincidencias para «{query}» (de {companies} empresas en el registro)');
    assert.match(page, /t\('research\.zeroMatches', \{ query, companies: formatNumber\(ordered\.length\) \}\)/, 'filtro sin coincidencias no pinta un rango 0-0');
    assert.equal(es.zeroMatches, '0 coincidencias para «{query}» (de {companies} empresas en el registro)');
    assert.match(page, /\{ordered\.length\s*\?/, 'el estado vacío depende del registro, no del filtro');
    assert.match(page, /title=\{t\('research\.emptyTitle'\)\}/, 'el estado sin empresas se conserva');
    assert.equal(es.emptyTitle, 'Todavía no hay ninguna empresa con research.');
    assert.match(page, /t\('research\.pageOf', \{ current: formatNumber\(slice\.page\), total: formatNumber\(slice\.pages\) \}\)/, 'posición de página declarada');
    assert.equal(es.pageOf, 'Página {current} de {total}');
});

void test('el buscador es un formulario GET accesible y las coincidencias vacías son honestas', () => {
    const page = readSource(PAGE);
    assert.match(page, /<form action="\/research"[^>]*method="get">/, 'filtro por GET: la URL cuenta el estado');
    assert.match(page, /htmlFor="research-index-q"/, 'label asociado al input');
    assert.match(page, /title=\{t\('research\.noMatchTitle', \{ query \}\)\}/, 'filtro sin resultados lo dice, no pinta un índice fantasma');
    const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
    assert.equal(es.noMatchTitle, 'Sin coincidencias para «{query}».');
    assert.match(page, /t\('research\.filterClear(Long)?'\)/, 'salida explícita del filtro');
    assert.equal(es.filterClear, 'Quitar filtro');
    assert.equal(es.filterClearLong, 'Quitar el filtro');
});
