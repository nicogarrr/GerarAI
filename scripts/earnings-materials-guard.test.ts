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
    assert.match(readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8'), /desde: addDays\(todayInMadrid\(\), -HISTORY_DAYS\)/);
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
