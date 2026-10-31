/**
 * Guard F286: /research/<ticker> fuera del master NUNCA devuelve 404 desde
 * este camino ni ofrece CTA «Generar tesis» sobre una identidad no
 * verificada. Procedencia exacta de la señal: getResearchCompanySnapshot solo
 * devuelve null ante el 404 de /api/companies/{ticker}/snapshot, y ese 404 en
 * backend es «compañía ausente del master» (resolve_company) — una empresa
 * del master sin research recibe snapshot construido. Política de veracidad:
 * ninguna respuesta del proveedor prueba la inexistencia del emisor buscado
 * (perfil {} = Finnhub no conoce el símbolo), y un perfil con nombre prueba
 * que el símbolo existe en alguna bolsa, no que sea ese emisor (ALM ->
 * Almonty US, no Almirall/BME). Tres estados honestos sin CTA.
 * Ejecución: node --experimental-strip-types --test scripts/research-unknown-ticker-guard.test.ts
 */
import test from 'node:test';
// @ts-expect-error TS5097
import { drainRejection } from '../lib/research/drain-rejection.ts';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { resolveUnknownListingIdentity } from '../lib/research/unknown-listing.ts';

void test('perfil sin nombre propio -> not-in-sources', () => {
    assert.deepEqual(resolveUnknownListingIdentity({}, 'ZZZZ'), { kind: 'not-in-sources' });
    assert.deepEqual(resolveUnknownListingIdentity({ name: '   ' }, 'ZZZZ'), { kind: 'not-in-sources' });
    assert.deepEqual(resolveUnknownListingIdentity({ name: 'ZZZZ' }, 'ZZZZ'), { kind: 'not-in-sources' });
});

void test('perfil del ticker desnudo con nombre -> unverified (emisor ambiguo)', () => {
    assert.deepEqual(
        resolveUnknownListingIdentity({ name: 'Almonty Industries' }, 'ALM'),
        { kind: 'unverified', providerName: 'Almonty Industries' },
    );
});

void test('proveedor no disponible -> unavailable', () => {
    assert.deepEqual(resolveUnknownListingIdentity(null, 'VZ'), { kind: 'unavailable' });
});

void test('la procedencia master-miss es exacta: null solo por 404 y 404 solo por compañía ausente', () => {
    // Frontend: getResearchCompanySnapshot devuelve null SOLO ante 404; el
    // resto de fallos se propaga (null no puede significar «error»).
    const actions: string = readFileSync(new URL('../lib/actions/research.actions.ts', import.meta.url), 'utf8');
    const fnStart = actions.indexOf('export async function getResearchCompanySnapshot');
    assert.ok(fnStart > -1);
    const fn = actions.slice(fnStart, actions.indexOf('\n}', fnStart));
    assert.match(fn, /error\.statusCode === 404\) return null/);
    assert.match(fn, /throw error/, 'los fallos que no son 404 deben propagarse');

    // Backend: /{ticker}/snapshot 404 solo cuando resolve_company no
    // encuentra la compañía; si existe, construye el snapshot (con o sin
    // research), así que snapshot null nunca es «master sin research».
    const routes: string = readFileSync(new URL('../data-engine/app/api/routes/companies.py', import.meta.url), 'utf8');
    const routeStart = routes.indexOf('"/{ticker}/snapshot"');
    assert.ok(routeStart > -1);
    const route = routes.slice(routeStart, routes.indexOf('@router.', routeStart));
    assert.match(route, /if not company:\s*\n\s*raise HTTPException\(status_code=404/);
    assert.match(route, /CompanySnapshotService\(\)\.build\(db, company\)/);
});

void test('la página pinta los tres estados sin 404, sin CTA y sin panel fuera del master', () => {
    const source: string = readFileSync(new URL('../app/(root)/research/[ticker]/page.tsx', import.meta.url), 'utf8');
    assert.ok(!source.includes('notFound'), 'este camino nunca devuelve 404 (ninguna respuesta prueba inexistencia)');

    const branchStart = source.indexOf('if (!snapshot) {');
    const branchEnd = source.indexOf('const company = snapshot.company;', branchStart);
    assert.ok(branchStart > -1 && branchEnd > branchStart, 'debe existir la rama if (!snapshot)');
    const branch = source.slice(branchStart, branchEnd);

    // La rama resuelve la identidad con el perfil del proveedor y pinta los
    // tres estados honestos.
    assert.match(branch, /resolveUnknownListingIdentity\(await getProfile\(ticker\), ticker\)/);
    // i18n: los textos viven en messages/<locale>/research.json (identity.*).
    for (const key of ['unverifiedTitle', 'unverifiedDesc', 'notInSourcesTitle', 'uncheckedTitle', 'searchOther']) {
        assert.ok(branch.includes(`t('research.identity.${key}'`), `la rama usa research.identity.${key}`);
    }
    const identity = JSON.parse(readFileSync(new URL('../lib/i18n/messages/es/research.json', import.meta.url), 'utf8')).identity;
    assert.equal(identity.unverifiedTitle, 'Identidad del ticker no verificada');
    assert.match(identity.unverifiedDesc, /puede no ser el emisor que buscas/);
    assert.equal(identity.notInSourcesTitle, 'No encontramos este ticker en nuestras fuentes');
    assert.equal(identity.uncheckedTitle, 'No pudimos comprobar este ticker');

    // Fuera del master no hay CTA de generación, ni panel de mercado N/D,
    // ni una segunda consulta al master (la señal ya es exacta).
    assert.ok(!branch.includes('<ThesisGenerateButton'), 'sin CTA de generación fuera del master');
    assert.equal(identity.searchOther, 'Buscar otra empresa', 'siguiente paso: buscar otra empresa');
    assert.match(branch, /Reintentar/, 'siguiente paso: reintentar la comprobación');
    assert.ok(!branch.includes('<CompanyMarketPanel'), 'sin panel N/D fuera del master');
    assert.ok(!branch.includes('getCompanyMarketSnapshot'), 'sin fetch de mercado fuera del master');
    assert.ok(!branch.includes('getResearchCompanyBasics'), 'sin segunda consulta al master: el 404 del snapshot ya es la señal');
});

void test('el drenaje se adjunta EN CREACIÓN, antes de cualquier await intermedio', () => {
    const page: string = readFileSync(new URL('../app/(root)/research/[ticker]/page.tsx', import.meta.url), 'utf8');
    const created = page.indexOf('const marketPromise =');
    const drainedMarket = page.indexOf('drainRejection(marketPromise)');
    const drainedMoat = page.indexOf('drainRejection(moatPromise)');
    const firstAwait = page.indexOf('snapshot = await snapshotPromise');
    assert.ok(created > -1 && drainedMarket > created && drainedMoat > created, 'drenaje tras crear las promesas');
    assert.ok(drainedMarket < firstAwait && drainedMoat < firstAwait, 'drenaje ANTES del primer await: sin ventana de unhandledRejection');
});

void test('drainRejection: sin unhandledRejection aunque nadie consuma, y el consumidor sigue recibiendo el error', async () => {
    let unhandled = 0;
    const listener = () => {
        unhandled += 1;
    };
    process.on('unhandledRejection', listener);
    try {
        drainRejection(Promise.reject(new Error('proveedor caído')));
        await new Promise((resolve) => setImmediate(resolve));
        await new Promise((resolve) => setImmediate(resolve));
        assert.equal(unhandled, 0, 'ningún rechazo queda sin manejar');
        const consumida = Promise.reject(new Error('el consumidor la ve'));
        drainRejection(consumida);
        await assert.rejects(consumida, /el consumidor la ve/, 'la propagación al consumidor no cambia');
    } finally {
        process.off('unhandledRejection', listener);
    }
});

void test('el diseño anti-homónimos sigue intacto en el snapshot de mercado', () => {
    const marketModule: string = readFileSync(new URL('../lib/actions/market-workspace.actions.ts', import.meta.url), 'utf8');
    assert.match(marketModule, /if \(!quoteSymbol\) \{/, 'quoteSymbolFor null debe seguir cortando antes del proveedor');
});


void test('los escapes E2E conocen los tres estados honestos', () => {
    // audit-closure vuelve antes si la ficha no ofrece workspace: los tres
    // estados de F286 deben estar en su lista o los tests exigirán controles
    // de tesis en una página que honestamente no los tiene.
    const spec: string = readFileSync(new URL('../e2e/audit-closure.spec.ts', import.meta.url), 'utf8');
    assert.match(spec, /Identidad del ticker no verificada/);
    assert.match(spec, /No encontramos este ticker/);
    assert.match(spec, /No pudimos comprobar este ticker/);
});

console.log('research-unknown-ticker-guard: ok');
