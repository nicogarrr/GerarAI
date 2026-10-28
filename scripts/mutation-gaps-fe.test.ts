import assert from 'node:assert/strict';
import test from 'node:test';
// Mutation testing (docs/testing/mutation.md): asserts que Stryker mostró ausentes.
// Cada test mata mutantes que sobrevivían en el baseline: si alguien rompe una
// etiqueta, un borde de sesión o el orden de N/D, estos tests lo pillan.
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
import { DCA_MIN_LEVEL_OPTIONS, DCA_STATUS_LABEL, dcaDataAge, dcaMissingBadge, dcaPercent, dcaPrice, dcaRsi, dcaRunSummary, dcaSignalMetric, dcaSkipReason } from '../lib/dca/format.ts';
// @ts-expect-error -- idem
import { classifyQuoteKind, mapBackendYahooQuote } from '../lib/market/quote-freshness.ts';
// @ts-expect-error -- idem
import { sortWatchlistRows } from '../lib/watchlist/sort-rows.ts';
// @ts-expect-error -- idem
import { buildAllocationSlices } from '../lib/portfolio-allocation.ts';

const t = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);
const now = (iso: string) => new Date(iso).getTime();

// ---------------------------------------------------------------- lib/dca/format
test('dca: etiquetas fijas del estado y del selector de nivel', () => {
    assert.deepEqual(DCA_STATUS_LABEL, { forming: 'en formación (provisional)', confirmed: 'confirmado' });
    assert.deepEqual(DCA_MIN_LEVEL_OPTIONS, [
        { value: 'global', label: 'Global' },
        { value: '1', label: '1X' },
        { value: '2', label: '2X' },
        { value: '3', label: '3X' },
        { value: '4', label: '4X' },
        { value: '0', label: 'Desactivado' },
    ]);
});

test('dca: porcentaje, precio y RSI con formato es-ES; no numérico o no finito = null', () => {
    assert.equal(dcaPercent(-0.1234), '-12,3\u00a0%');
    assert.equal(dcaPrice(1234.5, 'EUR'), '1234,50 EUR');
    assert.equal(dcaPrice(12345.678, null), '12.345,68');
    assert.equal(dcaRsi(28.46), '28,5');
    assert.equal(dcaRsi(30), '30');
    for (const bad of ['0.1', NaN, Infinity, -Infinity, null, undefined]) {
        assert.equal(dcaPercent(bad as never), null, `dcaPercent(${String(bad)})`);
        assert.equal(dcaRsi(bad as never), null, `dcaRsi(${String(bad)})`);
        assert.equal(dcaPrice(bad as never, 'USD'), null, `dcaPrice(${String(bad)})`);
    }
});

test('dca: métrica de la señal (sma_gap con/sin meses, caída de máximos, nada)', () => {
    const st = (metrics: unknown) => ({ metrics } as never);
    assert.deepEqual(dcaSignalMetric(st({ signal: 'sma_gap', sma_gap: -0.2, drawdown: -0.4 }), 24), { label: 'Distancia bajo media 24m', value: '-20,0\u00a0%' });
    assert.deepEqual(dcaSignalMetric(st({ signal: 'sma_gap', sma_gap: -0.2 }), null), { label: 'Distancia bajo media larga', value: '-20,0\u00a0%' });
    // sma_gap sin valor: cae a la caída desde máximos, no a «Distancia» vacía.
    assert.deepEqual(dcaSignalMetric(st({ signal: 'sma_gap', sma_gap: null, drawdown: -0.4 }), 24), { label: 'Caída desde máximo 36m', value: '-40,0\u00a0%' });
    assert.deepEqual(dcaSignalMetric(st({ signal: 'drawdown', sma_gap: -0.2, drawdown: -0.4 }), 24), { label: 'Caída desde máximo 36m', value: '-40,0\u00a0%' });
    assert.equal(dcaSignalMetric(st(undefined), 24), null);
    assert.equal(dcaSignalMetric(st({ signal: 'sma_gap' }), 24), null);
});

test('dca: edad de los datos', () => {
    assert.equal(dcaDataAge(0.9), 'hoy');
    assert.equal(dcaDataAge(1.2), 'hace 1 día');
    assert.equal(dcaDataAge(9.7), 'hace 9 días');
    for (const bad of [-1, NaN, Infinity, null, undefined]) assert.equal(dcaDataAge(bad as never), null);
});

test('dca: motivo de omisión', () => {
    assert.equal(dcaSkipReason(null), 'omitido');
    assert.equal(dcaSkipReason(''), 'omitido');
    assert.equal(dcaSkipReason('datos_desactualizados'), 'datos de precio demasiado viejos');
    assert.equal(dcaSkipReason('sin_datos'), 'sin datos de precio');
    assert.equal(dcaSkipReason('historia_insuficiente'), 'historia insuficiente');
    assert.equal(dcaSkipReason('otra_cosa'), 'otra_cosa');
});

test('dca: badge de ticker sin nivel, por estado', () => {
    const b = (item: unknown) => dcaMissingBadge(item as never);
    assert.deepEqual(b({ evaluation_status: 'job_failed', evaluation_reason: 'timeout' }), {
        text: 'Evaluación fallida', title: 'La última evaluación falló para este ticker: timeout.', tone: 'error',
    });
    assert.equal(b({ evaluation_status: 'job_failed' }).title, 'La última evaluación falló para este ticker.');
    assert.deepEqual(b({ evaluation_status: 'skipped', evaluation_reason: 'sin_datos' }), {
        text: 'Omitido', title: 'La evaluación lo omitió: sin datos de precio.', tone: 'warn',
    });
    assert.equal(b({ evaluation_status: 'skipped' }).title, 'La evaluación lo omitió: omitido.');
    assert.deepEqual(b({ evaluation_status: 'running' }), {
        text: 'En curso', title: 'Hay una evaluación en curso; el nivel aparecerá al terminar.', tone: 'neutral',
    });
    assert.deepEqual(b({ evaluation_status: 'pending' }), {
        text: 'Pendiente',
        title: 'Hay una ejecución registrada, pero este ticker no figuraba en ella (por ejemplo, añadido después). Se evaluará en la siguiente.',
        tone: 'neutral',
    });
    assert.equal(b({ evaluation_status: 'unknown' }).tone, 'warn');
    const never = {
        text: 'Sin evaluar',
        title: 'No consta ninguna evaluación ejecutada. Se evalúa tras el cierre (L-V) o con «Evaluar ahora».',
        tone: 'neutral',
    };
    assert.deepEqual(b(undefined), never);
    assert.deepEqual(b({}), never);
});

test('dca: resumen de la última ejecución (hora de Madrid, origen, tono)', () => {
    const run = (o: Record<string, unknown>) => dcaRunSummary({
        status: 'ok', trigger: 'scheduler', started_at: '2026-10-27T21:00:00Z', finished_at: '2026-10-27T21:05:00Z',
        tracked: 10, evaluated: 10, skipped: 0, errors: 0, alerted: 0, error: null, ...o,
    } as never);
    assert.deepEqual(dcaRunSummary(null), { text: 'Última ejecución: ninguna registrada todavía', tone: 'neutral' });
    assert.deepEqual(run({}), { text: 'Última ejecución (automática, 27 oct, 22:05): 10 de 10 evaluados', tone: 'ok' });
    // Sin finished_at usa started_at.
    assert.deepEqual(run({ status: 'running', trigger: 'manual', finished_at: null }), { text: 'Evaluación manual en curso desde 27 oct, 22:00', tone: 'neutral' });
    assert.deepEqual(run({ status: 'interrupted' }), { text: 'Última ejecución (automática, 27 oct, 22:05) interrumpida: no llegó a terminar', tone: 'error' });
    assert.deepEqual(run({ status: 'error', error: 'boom' }), { text: 'Última ejecución (automática, 27 oct, 22:05) falló: boom', tone: 'error' });
    assert.deepEqual(run({ status: 'error' }), { text: 'Última ejecución (automática, 27 oct, 22:05) falló', tone: 'error' });
    assert.deepEqual(run({ skipped: 2, evaluated: 8 }), { text: 'Última ejecución (automática, 27 oct, 22:05): 8 de 10 evaluados, 2 omitidos', tone: 'warn' });
    assert.deepEqual(run({ errors: 1 }), { text: 'Última ejecución (automática, 27 oct, 22:05): 10 de 10 evaluados, 1 con error', tone: 'warn' });
});

// ---------------------------------------------------- lib/market/quote-freshness
test('frescura: minutos respetados en la apertura (9:40 ET a las 9:50 ET es live)', () => {
    // Miércoles 30-sep-2026, EDT (UTC-4): 9:40 ET = 13:40Z.
    assert.equal(classifyQuoteKind(t('2026-09-30T13:40:00Z'), now('2026-09-30T13:50:00Z')), 'live');
    // Bordes exactos: t justo en la apertura = live; antes = stale.
    assert.equal(classifyQuoteKind(t('2026-09-30T13:30:00Z'), now('2026-09-30T13:31:00Z')), 'live');
    assert.equal(classifyQuoteKind(t('2026-09-30T13:29:00Z'), now('2026-09-30T13:31:00Z')), 'stale');
});

test('frescura: margen de 15 min para relojes adelantados', () => {
    assert.equal(classifyQuoteKind(t('2026-09-30T15:05:00Z'), now('2026-09-30T15:00:00Z')), 'live');
    assert.equal(classifyQuoteKind(t('2026-09-30T15:16:00Z'), now('2026-09-30T15:00:00Z')), 'stale');
    assert.equal(classifyQuoteKind(0, now('2026-09-30T15:00:00Z')), 'stale');
    assert.equal(classifyQuoteKind(NaN, now('2026-09-30T15:00:00Z')), 'stale');
});

test('frescura: el viernes es día de sesión (cierre del jueves en sesión del viernes = stale)', () => {
    assert.equal(classifyQuoteKind(t('2026-10-01T19:30:00Z'), now('2026-10-02T15:00:00Z')), 'stale');
});

test('frescura: justo al cierre (16:00 ET) la sesión de hoy pasa a close', () => {
    assert.equal(classifyQuoteKind(t('2026-09-30T19:59:00Z'), now('2026-09-30T20:00:00Z')), 'close');
    assert.equal(classifyQuoteKind(t('2026-09-30T13:30:00Z'), now('2026-09-30T20:00:00Z')), 'close');
});

test('frescura: tras el cierre, una cotización de AYER es stale (no un cierre válido)', () => {
    // Martes 29-sep 21:00Z (17:00 ET); t = lunes 28-sep 15:00 ET.
    assert.equal(classifyQuoteKind(t('2026-09-28T19:00:00Z'), now('2026-09-29T21:00:00Z')), 'stale');
});

test('frescura: el sábado, un cierre del jueves es stale (la referencia es el viernes)', () => {
    assert.equal(classifyQuoteKind(t('2026-10-01T20:00:00Z'), now('2026-10-03T15:00:00Z')), 'stale');
    // Domingo: igual, referencia el viernes.
    assert.equal(classifyQuoteKind(t('2026-10-01T20:00:00Z'), now('2026-10-04T15:00:00Z')), 'stale');
    // Martes pre-market: referencia el lunes; el viernes ya es stale.
    assert.equal(classifyQuoteKind(t('2026-10-02T20:00:00Z'), now('2026-10-06T12:00:00Z')), 'stale');
});

test('Yahoo backend: null/sin precio = null, d/dp no finitos = N/D (null), h/l/o no finitos = 0, fuente y tipo fijos', () => {
    assert.equal(mapBackendYahooQuote(null), null);
    assert.equal(mapBackendYahooQuote({ c: 0, pc: 0 }), null);
    assert.deepEqual(mapBackendYahooQuote({ c: 10, d: NaN, dp: Infinity, h: '11', l: 9, o: 9.5, pc: 9.8, cd: '2026-10-02' } as never), {
        c: 10, d: null, dp: null, h: 0, l: 9, o: 9.5, pc: 9.8,
        source: 'Yahoo Finance', t: null, kind: 'close', closeDate: '2026-10-02',
    });
    assert.equal(mapBackendYahooQuote({ pc: 5, cd: '2026-02-30' })?.closeDate, null);
});

// ------------------------------------------------------ lib/watchlist/sort-rows
test('watchlist: «added» hunde las filas sin precio y conserva el resto del orden', () => {
    const rows = [{ id: 'a', price: null }, { id: 'b', price: 2 }, { id: 'c', price: null }, { id: 'd', price: 1 }];
    assert.deepEqual(sortWatchlistRows(rows, 'added', 'asc', () => null).map((r: { id: string }) => r.id), ['b', 'd', 'a', 'c']);
});

test('watchlist: N/D al final en ambas direcciones y empates entre N/D estables', () => {
    const rows = [
        { id: 'n1', price: 1, v: null }, { id: 'x', price: 1, v: 3 }, { id: 'n2', price: 1, v: null },
        { id: 'y', price: 1, v: 1 }, { id: 'n3', price: 1, v: null },
    ];
    const ids = (dir: 'asc' | 'desc') => sortWatchlistRows(rows, 'pe', dir, (r: { v: number | null }) => r.v).map((r: { id: string }) => r.id);
    assert.deepEqual(ids('asc'), ['y', 'x', 'n1', 'n2', 'n3']);
    assert.deepEqual(ids('desc'), ['x', 'y', 'n1', 'n2', 'n3']);
});

test('watchlist: métricas de texto (fecha de resultados) se ordenan como texto', () => {
    const rows = [{ id: 'b', price: 1, v: '2026-11-05' }, { id: 'a', price: 1, v: '2026-10-30' }, { id: 'c', price: 1, v: '2027-01-15' }];
    const ids = (dir: 'asc' | 'desc') => sortWatchlistRows(rows, 'earnings', dir, (r: { v: string }) => r.v).map((r: { id: string }) => r.id);
    assert.deepEqual(ids('asc'), ['a', 'b', 'c']);
    assert.deepEqual(ids('desc'), ['c', 'b', 'a']);
});

// ------------------------------------------------------ lib/portfolio-allocation
test('distribución: posiciones a valor 0 dan 0 %, nunca NaN', () => {
    const slices = buildAllocationSlices([
        { symbol: 'A', value: 0, gain: 0, gainPercent: 0 },
        { symbol: 'B', value: 0, gain: 0, gainPercent: 0 },
    ]);
    assert.deepEqual(slices.map((s: { percentage: number }) => s.percentage), [0, 0]);
});
