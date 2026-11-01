import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { RATING_LABELS_EN, STATUS_LABELS_EN } from '../lib/research/status-labels-en.ts';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const keysOf = (name: string): string[] => {
  const start = page.indexOf(`const ${name}: Record<string, string> = {`);
  const body = page.slice(start, page.indexOf('\n};', start));
  return [...body.matchAll(/^\s{2}(?:'([^']+)'|([a-z_]+)):/gm)].map((m) => m[1] ?? m[2]);
};

test('los catálogos EN cubren exactamente las claves de STATUS_LABELS y RATING_LABELS', () => {
  const status = keysOf('STATUS_LABELS');
  const rating = keysOf('RATING_LABELS');
  assert.ok(status.length > 30 && rating.length >= 12);
  assert.deepEqual(Object.keys(STATUS_LABELS_EN).sort(), [...status].sort());
  assert.deepEqual(Object.keys(RATING_LABELS_EN).sort(), [...rating].sort());
});

test('label() sin locale conserva el ES histórico y con en usa los catálogos EN', () => {
  assert.match(page, /function label\(value: string \| null \| undefined, locale: Locale = 'es'\): string/);
  assert.match(page, /if \(locale === 'en'\) return STATUS_LABELS_EN\[value\] \?\? RATING_LABELS_EN\[value\]/);
  assert.match(page, /return STATUS_LABELS\[value\] \?\? RATING_LABELS\[value\] \?\? etiquetaValor\(value\);/);
  assert.equal(STATUS_LABELS_EN.partial, 'partial');
  assert.equal(STATUS_LABELS_EN.insufficient_data, 'insufficient data');
});

test('blockerLabel: firma con locale y catálogo EN con las mismas tres claves', () => {
  const src = readFileSync('lib/research/valuation-display.ts', 'utf8');
  assert.match(src, /export function blockerLabel\(id: string, locale: 'es' \| 'en' = 'es'\): string/);
  for (const key of ['traceable_wacc', 'forecast_is_not_the_driver', 'inferred_fcf_margin_target']) {
    assert.equal((src.match(new RegExp(`^  ${key}:`, 'gm')) ?? []).length, 2, key);
  }
});

test('las vistas del tramo 1 pasan el locale a label() y blockerLabel()', () => {
  assert.match(page, /label\(metric\.status, locale\)/);
  assert.match(page, /label\(valuation\.status \?\? 'unknown', locale\)/);
  assert.match(page, /blockers\.map\(\(id\) => blockerLabel\(id, locale\)\)/);
  assert.match(page, /label\(opportunity\.verdict\.label, locale\)/);
});
