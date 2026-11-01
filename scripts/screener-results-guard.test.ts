import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const adHoc = readFileSync('app/(root)/screeners/page.tsx', 'utf8') + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/screener.json', 'utf8')).screens);
const saved = readFileSync('app/(root)/screeners/[screenId]/page.tsx', 'utf8');
const formatter = readFileSync('lib/screener-results.ts', 'utf8');
test('ambas vistas muestran coincidencias y aceptan rank Decimal string', () => {
  for (const page of [adHoc, saved]) {
    assert.ok(page.includes('result.results.filter(row => row.matched)'));
    assert.ok(page.includes('formatScreenRank(row.rank_value, result.ranking_formula)'));
  }
  assert.ok(formatter.includes('formatCompact(value'));
  assert.ok(formatter.includes('Number.isFinite(Number(value))'));
});
test('cabeceras tienen separación y no rompen etiquetas', () => {
  assert.ok(adHoc.includes('px-3 py-2 whitespace-nowrap'));
});
test('la columna Coincidencia muestra el valor real de cada criterio, no un chip literal', () => {
  assert.ok(!adHoc.includes("t('screener.match')"), 'chip literal «coincidencia» aún presente');
  assert.ok(adHoc.includes('formatScreenCriterionValue(criterion.left_value)'));
  assert.ok(formatter.includes('formatScreenCriterionValue'));
});
