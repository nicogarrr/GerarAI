import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Explicit TS extension for strip types.
import { analysisStatusLabel } from '../lib/tracked-analysis-status.ts';
test('queued and insufficient data never claim complete valuation', () => {
  const as_of = '2026-10-18T00:00:00Z';
  assert.equal(analysisStatusLabel({status:'queued',as_of}), 'Analizando');
  assert.equal(analysisStatusLabel({status:'succeeded',as_of,thesis_status:'insufficient_data'}), 'Análisis: faltan datos');
  assert.equal(analysisStatusLabel({status:'dispatch_failed',as_of}), 'Análisis pendiente de reintento');
  assert.equal(analysisStatusLabel(null), null);
});
