/**
 * Calendario de resultados: registro IR, historia y que la SEC no dependa del frontend.
 * La logica SEC (emparejado, periodo, clasificacion) se prueba en data-engine/tests/test_earnings_materials_service.py.
 * Ejecucion: node --experimental-strip-types --test scripts/earnings-materials-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { irLinksFor, IR_REGISTRY } from '../lib/ir-registry.ts';

test('el calendario no depende de la SEC: acciones sin red propia, Suspense y fallo tragado', () => {
    const page = readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8');
    assert.match(page, /<Suspense/);
    const action = readFileSync('lib/actions/earnings-materials.actions.ts', 'utf8');
    assert.ok(action.includes('/api/calendar/followed/materials'));
    assert.ok(!/sec\.gov|User-Agent|SEC_USER_AGENT/i.test(action));
    assert.match(action, /catch \{\s*return \{\};/);
    const row = readFileSync('components/calendar/FollowedEarningsList.tsx', 'utf8');
    assert.ok(row.includes("materials.status === 'sin_cobertura_sec' || materials.status === 'periodo_no_coincide'"));
    assert.ok(row.includes("materials.status === 'no_disponible'"));
});

test('historia: la pagina pide los ultimos dias y el backend solo sirve historia confirmada', () => {
    const page = readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8');
    // La fecha de Madrid se calcula una sola vez para no cruzar medianoche entre rangos.
    assert.match(page, /const today = todayInMadrid\(\);/);
    assert.match(page, /desde: addDays\(today, -HISTORY_DAYS\)/);
    const svc = readFileSync('data-engine/app/services/earnings_dates_service.py', 'utf8');
    assert.match(svc, /return row\.confirmed is True/);
});

test('registro IR: pagina de evento solo con fecha exacta; si no, seccion general; sin entrada = nada', () => {
    assert.equal(irLinksFor('META', '2026-10-21')?.eventPage?.url, 'https://investor.atmeta.com/investor-events/event-details/2026/Q3-2026-Earnings-Call/default.aspx');
    assert.equal(irLinksFor('META', '2026-10-22')?.eventPage, null);
    assert.equal(irLinksFor('TSLA', '2026-10-21')?.eventPage, null);
    assert.equal(irLinksFor('ZZZZ', '2026-10-21'), null);
    for (const entry of Object.values(IR_REGISTRY)) {
        for (const url of [entry.section.url, ...entry.events.map((e) => e.url)]) assert.match(url, /^https:\/\//);
        assert.match(entry.verifiedOn, /^\d{4}-\d{2}-\d{2}$/);
    }
});

test('calendario: el historial dice "Resultados recientes" y el pie no afirma que la fecha no este publicada', () => {
    const page = readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8');
    // Las cadenas visibles viven en el diccionario i18n (carril C); la
    // página las referencia por clave. El guard verifica ambos extremos.
    const esEarnings = JSON.parse(readFileSync('lib/i18n/messages/es/calendar.json', 'utf8')).earnings;
    assert.ok(page.includes('calendar.earnings.recentTitle'));
    assert.equal(esEarnings.recentTitle, 'Resultados recientes (últimos {days} días)');
    assert.ok(page.includes('calendar.earnings.withoutDate'));
    assert.match(esEarnings.withoutDate, /^Sin fecha vigente en el calendario: /);
    assert.ok(page.includes('calendar.earnings.staleDates'));
    assert.match(esEarnings.staleDates, /^Fecha pendiente de actualizar/);
    for (const banned of ['Publicados en los últimos', 'Sin fecha publicada', 'aún sin publicar']) {
        assert.ok(!page.includes(banned) && !JSON.stringify(esEarnings).includes(banned), `prohibido: "${banned}"`);
    }
});

test('registro IR: BN T2 enlaza grabacion y transcripcion solo con fecha exacta', () => {
    const hit = irLinksFor('BN', '2026-08-13');
    assert.deepEqual(hit?.eventPage?.assets.map((a) => a.kind), ['grabacion', 'transcripcion']);
    for (const a of hit?.eventPage?.assets ?? []) assert.ok(a.url.startsWith('https://bn.brookfield.com/') && a.source.startsWith('https://bn.brookfield.com/events/'));
    assert.equal(irLinksFor('BN', '2026-08-14')?.eventPage, null);
    assert.deepEqual(irLinksFor('BN', '2026-11-12')?.eventPage?.assets, []);
});

test('registro IR: META T1 enlaza presentacion y transcripcion (fecha exacta); T3 aun sin archivos', () => {
    assert.deepEqual(irLinksFor('META', '2026-04-29')?.eventPage?.assets.map((a) => a.kind), ['presentacion', 'transcripcion']);
    assert.deepEqual(irLinksFor('META', '2026-10-21')?.eventPage?.assets.map((a) => a.kind), ['webcast', 'presentacion']);
});

test('registro IR: el tooltip no atribuye extraccion de una pagina fuente no leida', () => {
    const list = readFileSync('components/calendar/FollowedEarningsList.tsx', 'utf8');
    const esEarnings = JSON.parse(readFileSync('lib/i18n/messages/es/calendar.json', 'utf8')).earnings;
    assert.ok(list.includes('calendar.earnings.irAssetTip') && list.includes('calendar.earnings.irTip'));
    assert.match(esEarnings.irAssetTip, /^Archivo oficial · verificado el /);
    assert.ok(!list.includes('anunciado en') && !JSON.stringify(esEarnings).includes('anunciado en'));
});
