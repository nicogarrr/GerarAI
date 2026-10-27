import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires explicit extension.
import { normalizeChartCandles } from '../lib/market/normalize-chart.ts';
// @ts-expect-error Node strip-types requires explicit extension.
import { dailyPivots, fibonacci, adx, structure } from '../lib/market/technical.ts';

test('REAL Yahoo adapter to REAL chart normalization preserves close-only abstention', () => {
    const t = Array.from({ length: 40 }, (_, i) => 1790000000 + i * 86400);
    const payload = { chart: { result: [{ timestamp: t, indicators: { quote: [{ close: t.map((_, i) => 100 + i), open: t.map(() => null), high: t.map(() => null), low: t.map(() => null), volume: t.map(() => null) }] } }] } };
    const python = spawnSync('python3', ['scripts/fixtures/yahoo-close-only-adapter.py'], { input: JSON.stringify(payload), encoding: 'utf8' });
    assert.equal(python.status, 0, python.stderr);
    const adapted = JSON.parse(python.stdout);
    assert.ok(adapted && adapted.s === 'ok', 'real adapter must return candles for the local fixture');
    assert.deepEqual(adapted.o, t.map(() => null));
    assert.deepEqual(adapted.h, t.map(() => null));
    assert.deepEqual(adapted.l, t.map(() => null));
    const bars = normalizeChartCandles(adapted, { from: 0, to: 2000000000, resolution: 'D' });
    assert.equal(bars.length, 40);
    assert.deepEqual(bars.map((bar) => bar.close), adapted.c);
    assert.ok(bars.every((bar) => bar.open === null && bar.high === null && bar.low === null));
    assert.deepEqual(dailyPivots(bars), []);
    assert.deepEqual(fibonacci(bars), []);
    assert.equal(adx(bars), null);
    assert.equal(structure(bars), 'Sin datos');
    assert.match(readFileSync('lib/actions/market-workspace.actions.ts', 'utf8'), /normalizeChartCandles\(candles,/);
});
