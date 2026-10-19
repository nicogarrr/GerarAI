/**
 * Quick win UX 6: /research ordenado por relevancia
 * (tesis > cartera > watchlist > resto).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { researchRelevanceKey, sortCompaniesByRelevance } from '../lib/research/relevance.ts';

const page = readFileSync('app/(root)/research/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');

test('los buckets de relevancia son tesis > cartera > watchlist > resto', () => {
    const portfolio = new Set(['COST']);
    const watchlist = new Set(['NFLX']);
    assert.equal(researchRelevanceKey('AAPL', true, portfolio, watchlist), 0);
    assert.equal(researchRelevanceKey('COST', true, portfolio, watchlist), 0, 'la tesis gana a la cartera');
    assert.equal(researchRelevanceKey('cost', false, portfolio, watchlist), 1, 'normalización');
    assert.equal(researchRelevanceKey('NFLX', false, portfolio, watchlist), 2);
    assert.equal(researchRelevanceKey('AAPL', false, portfolio, watchlist), 3);
});

test('el orden es estable: bucket y luego ticker', () => {
    const companies = [{ ticker: 'ZZZ' }, { ticker: 'AAA' }, { ticker: 'MID' }, { ticker: 'TESIS' }];
    const ordered = sortCompaniesByRelevance(
        companies,
        (company) => company.ticker === 'TESIS',
        new Set(['ZZZ']),
        new Set(['MID']),
    );
    assert.deepEqual(ordered.map((company) => company.ticker), ['TESIS', 'ZZZ', 'MID', 'AAA']);
    assert.deepEqual(companies.map((company) => company.ticker), ['ZZZ', 'AAA', 'MID', 'TESIS'], 'no muta la entrada');
});

test('la página degrada sin fabricar pertenencia ni tesis', () => {
    // Lectura de tesis fallida (null): el bucket queda vacío, nunca afirma
    // tesis inexistentes.
    assert.match(page, /new Set\(thesisTickers \?\? \[\]\)/);
    assert.match(page, /thesisSet\.has\(company\.ticker\.trim\(\)\.toUpperCase\(\)\)/);
    // Lecturas de contexto degradan a vacío, no a badges/orden fabricados.
    assert.match(page, /getResearchPortfolioPositions\(\)\.catch\(\(\) => \[\]\)/);
    assert.match(page, /getWatchlist\(\)\.catch\(\(\) => \[\]/);
    // Solo posiciones abiertas cuentan como cartera (misma semántica que los badges).
    assert.match(readFileSync('lib/research/portfolio-membership.ts', 'utf8'), /row\.quantity !== 0/);
});

test('el bucket tesis sale de UNA query DISTINCT, no de un snapshot por empresa', () => {
    // Endpoint ligero del backend (misma semántica que latest_thesis del
    // snapshot) consumido por el dashboard; la página NO ordena mirando
    // snapshots de todas las empresas.
    assert.match(actions, /\/api\/companies\/thesis-tickers/);
    assert.doesNotMatch(page, /latest_thesis != null/);
    assert.match(page, /sortCompaniesByRelevance\(/);
});

test('los snapshots son solo de la página visible y un lote fallido se aísla', () => {
    assert.match(page, /SNAPSHOT_BATCH_SIZE = 50/);
    // El fetch de snapshots va DESPUÉS de filtrar y paginar: solo la página
    // visible pide detalle.
    assert.ok(
        page.indexOf('paginateResearchIndex(filtered') < page.indexOf('fetchInBatches('),
        'los snapshots se piden tras paginar',
    );
    assert.match(page, /fetchInBatches\(\s*sliceTickers,/);
    // Una sola llamada al endpoint (dentro del helper de lotes).
    assert.equal((page.match(/getResearchCompanySnapshots\(/g) ?? []).length, 1);
    // El lote caído marca sus tarjetas como no leídas, nunca fabrica snapshots.
    assert.match(page, /part === null/);
    assert.match(page, /unreadableTickers\.add\(ticker\)/);
});
