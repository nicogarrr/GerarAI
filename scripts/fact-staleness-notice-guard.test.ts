/**
 * QA datos (hallazgo 6): JPM presentaba «efectivo» de 2018 y «deuda total»
 * de 2013 junto a ingresos de 2025 como si fuesen el estado actual. La foto
 * de balance más reciente ahora lleva aviso cuando va más de un ejercicio
 * por detrás del último dato de la empresa; el número sigue visible (es la
 * historia real), pero nadie lo lee como «hoy».
 *
 * Ejecucion: node --experimental-strip-types --test scripts/fact-staleness-notice-guard.test.ts
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { factStalenessNotice } from '../lib/research/fact-display-audit.ts';

const jpmCash = { metric: 'cash_and_equivalents', fiscal_year: 2018 };
const jpmDebt = { metric: 'total_debt', fiscal_year: 2013 };

test('la última foto de balance muy por detrás lleva aviso', () => {
  assert.match(factStalenessNotice(jpmCash, { isLatestForMetric: true, latestFiscalYear: 2025 })!, /2018/);
  assert.match(factStalenessNotice(jpmDebt, { isLatestForMetric: true, latestFiscalYear: 2025 })!, /2013/);
});

test('no avisa cuando el dato es reciente, histórico o no es de balance', () => {
  // fila histórica (no la última de la métrica): su antigüedad es evidente
  assert.equal(factStalenessNotice(jpmCash, { isLatestForMetric: false, latestFiscalYear: 2025 }), null);
  // tolerancia de un ejercicio (calendarios fiscales distintos)
  assert.equal(factStalenessNotice({ metric: 'total_debt', fiscal_year: 2024 }, { isLatestForMetric: true, latestFiscalYear: 2025 }), null);
  // series temporales (ingresos, BPA) no son una foto de estado actual
  assert.equal(factStalenessNotice({ metric: 'revenue', fiscal_year: 2018 }, { isLatestForMetric: true, latestFiscalYear: 2025 }), null);
  // sin año fiscal o sin referencia de empresa no se puede juzgar
  assert.equal(factStalenessNotice({ metric: 'total_debt', fiscal_year: null }, { isLatestForMetric: true, latestFiscalYear: 2025 }), null);
  assert.equal(factStalenessNotice(jpmCash, { isLatestForMetric: true, latestFiscalYear: null }), null);
});

test('las tarjetas y la tabla de hechos muestran el aviso junto al valor', () => {
  const page = readFileSync('components/research/FactsPanels.tsx', 'utf8');
  assert.match(page, /factStalenessNotice\(fact, \{ isLatestForMetric:/);
  assert.match(page, /staleness=\{stalenessOf\(fact\)\}/);
  assert.match(page, /\{stalenessOf\(fact\) \? <span className="mt-1 block text-xs text-amber-300">/);
});
