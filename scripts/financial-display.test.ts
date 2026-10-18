import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { financialDefinition, financialFormula, financialPeriod, financialSegment, financialVersion, loadedFinancialRange } from '../lib/research/financial-display.ts';

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

test('las fórmulas del marco traducen métricas sin alterar umbrales', () => {
  const text = financialFormula('V1 checks (fcf_margin_5y > 0.05, roe_5y > 0.15) plus owner_earnings_5y > 0');
  assert.ok(text.includes('criterios de la versión 1'));
  assert.ok(text.includes('ROE (5 años) > 0.15'));
  assert.ok(text.includes('Beneficio del propietario (5 años) > 0'));
});

test('versiones y rango corresponden a datos cargados, no a la ventana solicitada', () => {
  assert.equal(financialVersion('MARCO_V2'), 'Marco de calidad · versión 2');
  assert.equal(financialVersion('FUTURE_V3'), 'FUTURE_V3');
  assert.equal(loadedFinancialRange([{ series: [{ period: 'FY2025', value: 12 }, { period: 'unknown', value: null }] }]), '2025');
  assert.equal(loadedFinancialRange([{ series: [{ period: 'unknown', value: null }] }]), null);
  assert.equal(loadedFinancialRange([{ series: [{ period: '2023-09-27:FY', value: 12 }, { period: 'FY2025', value: 20 }] }]), '2023–2025');
});
