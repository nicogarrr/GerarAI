import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS, metricLabel } from '../lib/research/metric-labels.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS_EN } from '../lib/research/metric-labels-en.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { FRAMEWORK_TERMS, frameworkTerm } from '../lib/research/framework-terms.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { FRAMEWORK_TERMS_EN } from '../lib/research/framework-terms-en.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { financialFormula, financialPeriod, financialVersionLabel } from '../lib/research/financial-display.ts';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

test('METRIC_LABELS_EN cubre exactamente las claves de METRIC_LABELS', () => {
  assert.ok(Object.keys(METRIC_LABELS).length > 140);
  assert.deepEqual(Object.keys(METRIC_LABELS_EN).sort(), Object.keys(METRIC_LABELS).sort());
});

test('metricLabel sin locale conserva el ES histórico; con en usa el catálogo EN', () => {
  assert.equal(metricLabel('net_debt_to_ebitda'), 'Deuda neta / EBITDA');
  assert.equal(metricLabel('free_cash_flow'), 'Flujo de caja libre');
  assert.equal(metricLabel('fx_rate:CNY/USD'), 'tipo de cambio CNY/USD');
  assert.equal(metricLabel('net_debt_to_ebitda', 'en'), 'Net debt / EBITDA');
  assert.equal(metricLabel('free_cash_flow', 'en'), 'Free cash flow');
  assert.equal(metricLabel('fx_rate:CNY/USD', 'en'), 'exchange rate CNY/USD');
  assert.equal(metricLabel('clave_desconocida', 'en'), 'clave desconocida');
});

test('las excepciones EN de framework-terms son claves reales y el ES no cambia', () => {
  for (const key of Object.keys(FRAMEWORK_TERMS_EN)) assert.ok(Object.hasOwn(FRAMEWORK_TERMS, key), key);
  assert.equal(frameworkTerm('standard_dcf'), 'DCF de flujo de caja libre');
  assert.equal(frameworkTerm('standard_dcf', 'en'), 'free cash flow DCF');
  assert.equal(frameworkTerm('churn', 'en'), 'customer churn');
  assert.equal(frameworkTerm('loan_growth', 'en'), 'loan growth');
  assert.equal(frameworkTerm('ARR × retention', 'en'), 'ARR × retention');
  assert.equal(frameworkTerm('desconocido_total', 'en'), null);
});

test('financial-display: ES histórico intacto y EN sin texto español', () => {
  assert.equal(financialPeriod('unknown'), 'Periodo no informado por la fuente');
  assert.equal(financialPeriod('2025-12-31:FY'), 'Ejercicio al 31/12/2025');
  assert.equal(financialPeriod('2025-09-30:Q3'), 'T3 al 30/09/2025');
  assert.equal(financialPeriod('unknown', 'en'), 'Period not reported');
  assert.equal(financialPeriod('2025-12-31:FY', 'en'), 'Fiscal year ended 2025-12-31');
  assert.equal(financialPeriod('2025-09-30:Q3', 'en'), 'Q3 ended 2025-09-30');
  assert.equal(financialVersionLabel('MARCO_V1'), 'Marco de calidad · versión 1');
  assert.equal(financialVersionLabel('MARCO_V1', 'en'), 'Quality framework · version 1');
  assert.equal(financialVersionLabel('X_V7'), 'cálculo v7');
  assert.equal(financialVersionLabel('X_V7', 'en'), 'calculation v7');
  assert.equal(financialVersionLabel('X', 'en'), 'unversioned calculation');
  assert.equal(financialFormula('net_income plus D&A'), 'Beneficio neto más D&A');
  assert.equal(financialFormula('net_income plus D&A', 'en'), 'net_income plus D&A');
});

test('la ficha pasa locale a metricLabel, termLabel y financial* y termLabel lo reenvía', () => {
  assert.match(panels, /export function termLabel\(raw: string, locale: 'es' \| 'en' = 'es'\): string/);
  assert.match(panels, /frameworkTerm\(raw, locale\) \?\? metricLabel\(raw, locale\)/);
  assert.match(page, /metricLabel\(metric\.metric, locale\)/);
  assert.match(page, /financialPeriod\(metric\.period, locale\)/);
  assert.match(page, /financialVersionLabel\(metric\.definition_version, locale\)/);
  assert.match(page, /financialFormula\(metric\.formula, locale\)/);
  assert.match(page, /termLabel\(valuation\.model_type, locale\)/);
  assert.equal((page.match(/termLabel\(item, locale\)/g) ?? []).length, 2);
  assert.doesNotMatch(page, /map\(termLabel\)/);
});
