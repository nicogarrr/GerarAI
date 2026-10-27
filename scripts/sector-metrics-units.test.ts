import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
// @ts-expect-error TS5097 node strip-types
import { calculateAverage, normalizeGrowthScore, normalizeProfitabilityScore } from '../lib/utils/sectorMetrics.ts';

describe('sector: contrato porcentual explicito, salidas en fraccion', () => {
  // Muestras sinteticas del contrato de profitabilityPoints (porcentaje crudo).
  for (const raw of [0.8, 0, -0.8, -20, 150]) {
    for (const alias of ['roeTTM', 'roaTTM', 'netProfitMarginTTM', 'revenueGrowthTTM', 'salesGrowth', 'returnOnEquity']) {
      it(`${alias} ${raw}% se divide exactamente una vez`, () => {
        assert.equal(calculateAverage([{ [alias]: raw }], [alias], 'percent'), raw / 100);
      });
    }
  }
  it('promedia fracciones del mismo contrato sin heuristicas de magnitud', () => {
    assert.equal(calculateAverage([{x: 0.8}, {x: 150}, {x: -20}], ['x'], 'percent'), (0.008 + 1.5 - 0.2) / 3);
  });
  it('PE/PB/PS/deuda/liquidez no se dividen', () => {
    assert.equal(calculateAverage([{roeTTM: 150}], ['roeTTM']), 150);
  });
  it('omite datos ausentes/no finitos y conserva cero', () => {
    assert.equal(calculateAverage([{x: null}, {x: Infinity}, {x: 'NaN'}, {x: 0}], ['x'], 'percent'), 0);
    assert.equal(calculateAverage([{x: null}], ['x'], 'percent'), null);
  });
  it('growth >100% no vuelve a dividirse al puntuar', () => {
    assert.equal(normalizeGrowthScore(1.5), 90);
    assert.equal(normalizeGrowthScore(0.008), 50);
    assert.equal(normalizeGrowthScore(-0.008), 30);
  });
  it('rentabilidad >100% conserva fraccion, negativos y ceros no puntuan positivo', () => {
    assert.equal(normalizeProfitabilityScore(1.5, 1.5, 1.5), 100);
    assert.equal(normalizeProfitabilityScore(-0.008, -0.008, -0.008), 0);
    assert.equal(normalizeProfitabilityScore(0, 0, 0), 0);
  });
});
