import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { financialDefinition, financialFormula, financialPeriod, financialSegment } from '../lib/research/financial-display.ts';

test('periodos mantienen el cierre fiscal y no inventan fechas para unknown', () => {
  assert.equal(financialPeriod('2025-09-27:FY'), 'Ejercicio al 27/09/2025');
  assert.equal(financialPeriod('2026-06-30:Q2'), 'T2 al 30/06/2026');
  assert.equal(financialPeriod('unknown'), 'Periodo sin identificar');
  assert.equal(financialPeriod('FY2021-FY2025'), 'Ejercicio 2021-Ejercicio 2025');
  assert.equal(financialPeriod('custom period'), 'custom period');
});

test('fórmulas mantienen operadores y advertencia sobre aproximaciones', () => {
  assert.equal(financialFormula('free_cash_flow / revenue'), 'Flujo de caja libre / Ingresos');
  assert.equal(financialFormula('future_metric * 0.05'), 'future_metric * 0.05');
  assert.equal(financialFormula('inflation-adjusted internal rate of return on gross investment; no proxy calculation is permitted'), 'Tasa interna de rentabilidad de la inversión bruta ajustada por inflación; no admite cálculos sustitutivos');
  assert.equal(financialSegment('consolidated'), 'Consolidado');
  assert.equal(financialSegment('North America'), 'North America');
});

test('definiciones conservan contenido y traducen los textos del backend', () => {
  assert.equal(financialDefinition('Operating cash flow less capital expenditure.'), 'Flujo de caja operativo menos inversión de capital.');
});
