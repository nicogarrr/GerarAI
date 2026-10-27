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

// @ts-expect-error TS5097 node strip-types
import { netMarginPoints, revenueGrowthPoints } from '../lib/utils/profitabilityPoints.ts';

describe('sector faltante no concede bonus relativo', () => {
  it('crecimiento positivo sin sector usa solo criterio absoluto', () => {
    assert.equal(revenueGrowthPoints(150, null), 25);
    assert.equal(revenueGrowthPoints(150, 0), 40);
  });
  it('margen sin sector no usa media imaginaria 15%', () => {
    assert.equal(netMarginPoints(150, null), 25);
    assert.equal(netMarginPoints(150, 0), 35);
    assert.equal(netMarginPoints(-0.8, null), 0);
  });
});

import { readFileSync } from 'node:fs';
it('contrato de salida: nueve medias no sustituyen missing por 0 ni scores por defaults', () => {
  const source = readFileSync('lib/actions/sectorData.actions.ts', 'utf8');
  for (const field of ['avgPE', 'avgPB', 'avgPS', 'avgROE', 'avgROA', 'avgNetMargin', 'avgRevenueGrowth', 'avgDebtToEquity', 'avgCurrentRatio']) {
    assert.match(source, new RegExp(`${field}: ${field}\\b`));
    assert.doesNotMatch(source, new RegExp(`${field} \\|\\|`));
  }
  const scoring = readFileSync('lib/utils/advancedStockScoring.ts', 'utf8');
  assert.match(scoring, /sectorGrowth !== null && growth/);
  assert.match(scoring, /sectorMargin !== null && margin/);
  assert.doesNotMatch(scoring, /avg(?:RevenueGrowth|NetMargin)\s*(?:\?\?|\|\|)\s*0\.15/);
});

it('sin sectorData: los deltas ausentes son null, nunca cero/empate', () => {
  const scoring = readFileSync('lib/utils/advancedStockScoring.ts', 'utf8');
  const absent = scoring.slice(scoring.indexOf('} : {\n        value: null, // Sin comparación disponible'));
  assert.ok(absent.length > 0);
  for (const field of ['value', 'growth', 'profitability', 'cashFlow', 'momentum', 'debtLiquidity']) {
    assert.match(absent.slice(0, absent.indexOf('};')), new RegExp(`${field}: null`));
  }
});
