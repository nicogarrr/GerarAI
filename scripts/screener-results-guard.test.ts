import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const adHoc = readFileSync('app/(root)/screeners/page.tsx', 'utf8');
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
