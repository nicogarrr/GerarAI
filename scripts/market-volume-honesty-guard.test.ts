/**
 * Guard F318: un volumen desconocido nunca se fabrica como 0.
 * Backend: /api/market/candles conserva null; frontend: las velas se tipan
 * con huecos (number | null) y normalize-chart los propaga como null.
 * (El análisis técnico de volumen se eliminó con getTechnicalAnalysis:
 * código muerto sin consumidores.)
 * Ejecución: node --experimental-strip-types --test scripts/market-volume-honesty-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

void test('estructura: el backend conserva null y el frontend tipa huecos', () => {
    const market = readFileSync('data-engine/app/api/routes/market.py', 'utf8');
    assert.ok(!market.includes('else 0.0)'), 'ningún volumen se fabrica como 0.0 en market.py');
    const finnhub = readFileSync('lib/actions/finnhub.actions.ts', 'utf8');
    assert.match(finnhub, /v: \(number \| null\)\[\]/);
    const workspace = readFileSync('lib/actions/market-workspace.actions.ts', 'utf8');
    assert.match(workspace, /normalizeChartCandles\(candles,/);
    assert.match(readFileSync('lib/market/normalize-chart.ts', 'utf8'), /volume: candles\.v\?\.\[index\] \?\? null/);
});
