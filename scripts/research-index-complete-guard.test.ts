/**
 * F179: el indice de /research se titula «Todas las empresas con research en
 * GerarAI», pero el listado salia de UNA llamada a /api/companies, cuyo
 * default es 100 fichas (tope 500). Con mas de 100 empresas el indice se
 * cortaba en silencio (A→AMBA) y «todas» mentia. Contratos fijados aqui:
 *  - el dashboard pide TODAS las paginas via paginateAll;
 *  - paginateAll TERMINA: pagina corta cierra, y si el backend ignora offset
 *    (pagina repetida) lanza error en vez de colgar o devolver parcial;
 *  - las subrutas que no listan empresas (workflows, settings) no cargan el
 *    indice completo: usan las acciones ligeras.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { paginateAll } from '../lib/paginate-all.ts';

const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');

test('el dashboard no pide /api/companies a pelo (default 100)', () => {
    const start = actions.indexOf('export async function getResearchDashboard()');
    assert.notEqual(start, -1, 'getResearchDashboard debe existir');
    assert.ok(
        !actions.slice(start).includes("getJson<ResearchCompany[]>('/api/companies'"),
        'una llamada sin limit/offset lista solo las 100 primeras empresas',
    );
});

test('el listado se completa paginando con paginateAll', () => {
    assert.match(actions, /paginateAll\(/);
    assert.match(actions, /offset=\$\{offset\}/);
});

test('la pagina pedida respeta el tope del backend (limit le=500)', () => {
    const match = actions.match(/const COMPANIES_PAGE_SIZE = (\d+);/);
    assert.ok(match, 'COMPANIES_PAGE_SIZE debe existir');
    assert.ok(Number(match[1]) <= 500, 'el backend rechaza limit > 500');
});

test('paginateAll devuelve las 2.115 fichas repartidas en 5 paginas', async () => {
    const total = 2115;
    const pageSize = 500;
    const fetchPage = async (offset: number) =>
        Array.from(
            { length: Math.max(0, Math.min(pageSize, total - offset)) },
            (_, i) => `T${offset + i}`,
        );
    const all = await paginateAll(fetchPage, pageSize, (t) => t);
    assert.equal(all.length, total);
    assert.equal(all[0], 'T0');
    assert.equal(all[total - 1], `T${total - 1}`);
});

test('paginateAll aborta si el backend repite pagina (nunca lista parcial)', async () => {
    const page = Array.from({ length: 500 }, (_, i) => `T${i}`);
    const fetchPage = async () => page; // ignora offset
    await assert.rejects(() => paginateAll(fetchPage, 500, (t) => t), /página repetida/);
});

test('paginateAll aborta si el backend cicla paginas distintas', async () => {
    const pages = [
        Array.from({ length: 500 }, (_, i) => `A${i}`),
        Array.from({ length: 500 }, (_, i) => `B${i}`),
    ];
    let n = 0;
    const fetchPage = async () => pages[n++ % 2];
    await assert.rejects(() => paginateAll(fetchPage, 500, (t) => t), /página repetida/);
});

