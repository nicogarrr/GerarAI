import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { nativePnlIfContradicts } from '../lib/portfolio-native-pnl.ts';

const base = { gainKnown: true, nativeCurrency: 'USD', baseCurrency: 'EUR' };

test('muestra la G/P nativa solo si el signo contradice la G/P en divisa base', () => {
  const r = nativePnlIfContradicts({ ...base, gain: -215.4, nativeGain: 120, nativeCost: 4000 });
  assert.deepEqual(r, { amount: 120, percent: 3, currency: 'USD' });
  assert.equal(nativePnlIfContradicts({ ...base, gain: 50, nativeGain: 120, nativeCost: 4000 }), null);
});

test('omite la línea si falta dato, hay misma divisa o G/P desconocida', () => {
  assert.equal(nativePnlIfContradicts({ ...base, gain: -1, nativeGain: null, nativeCost: 10 }), null);
  assert.equal(nativePnlIfContradicts({ ...base, gain: -1, nativeGain: 5, nativeCost: 10, nativeCurrency: 'EUR' }), null);
  assert.equal(nativePnlIfContradicts({ ...base, gainKnown: false, gain: -1, nativeGain: 5, nativeCost: 10 }), null);
  assert.equal(nativePnlIfContradicts({ ...base, gain: -1, nativeGain: 5, nativeCost: null })?.percent, null);
});
