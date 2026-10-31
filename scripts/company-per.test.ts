import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { perState } from '../lib/research/per.ts';

const base = { ticker: 'KO', providerAvailable: true };

test('PER solo con dato positivo y verificable del listado US', () => {
  assert.equal(perState({ ...base, quoteSymbol: 'KO', peTTM: 26.4 }).value, 26.4);
});

test('sin dato verificable el PER es null con motivo, nunca 0 ni inventado', () => {
  for (const peTTM of [undefined, null, 0, -3, Number.NaN, '26']) {
    const state = perState({ ...base, quoteSymbol: 'KO', peTTM });
    assert.equal(state.value, null);
    assert.ok(state.note);
  }
});

test('un listado no-US o sin mapear no usa el PER del ADR/homónimo', () => {
  assert.equal(perState({ ticker: 'ASML', quoteSymbol: 'ASML.AS', peTTM: 40, providerAvailable: true }).value, null);
  assert.equal(perState({ ticker: 'ASML', quoteSymbol: null, peTTM: 40, providerAvailable: true }).value, null);
});

test('la ficha enseña el PER con su motivo', async () => {
  const { readFileSync } = await import('node:fs');
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.match(page, /getCompanyPer\(/);
  assert.match(page, /research\.fichaPerTtm/);
  assert.match(page, /research\.fichaPerUnavailable/);
});
