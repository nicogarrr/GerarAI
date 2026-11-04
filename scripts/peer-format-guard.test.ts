import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { formatPeerValue, peerMedianText } from '../lib/research/peer-format.ts';

test('un valor ausente nunca se muestra como 0', () => {
  assert.equal(formatPeerValue(null, 'roe'), 'Sin datos');
  assert.equal(formatPeerValue(undefined, 'roe'), 'Sin datos');
  assert.equal(formatPeerValue('abc', 'roe'), 'Sin datos');
});

test('ratios en % con coma española y deuda/EBITDA en x', () => {
  assert.equal(formatPeerValue('0.1234', 'net_margin'), '12,3 %');
  assert.equal(formatPeerValue('1.5', 'net_debt_to_ebitda'), '1,50x');
  assert.equal(formatPeerValue('0', 'roe'), '0,0 %');
});

test('n<3 muestra la nota y no una mediana', () => {
  assert.equal(
    peerMedianText({ peer_median: null, insufficient_sample: true, note: 'muestra insuficiente (n<3)' }, 'roe'),
    'muestra insuficiente (n<3)',
  );
  assert.equal(peerMedianText({ peer_median: '0.2', insufficient_sample: false }, 'roe'), '20,0 %');
  assert.equal(peerMedianText({ peer_median: null }, 'roe'), 'Sin datos');
});

test('inglés (Ajustes → Idioma): «12.3%», «1.50x», «No data» y la nota del backend traducida', () => {
  assert.equal(formatPeerValue('0.1234', 'net_margin', 'en'), '12.3%');
  assert.equal(formatPeerValue('1.5', 'net_debt_to_ebitda', 'en'), '1.50x');
  assert.equal(formatPeerValue(null, 'roe', 'en'), 'No data');
  assert.equal(
    peerMedianText({ peer_median: null, insufficient_sample: true, note: 'muestra insuficiente (n<3)' }, 'roe', 'en'),
    'insufficient sample (n<3)',
  );
  assert.equal(peerMedianText({ peer_median: '0.2', insufficient_sample: false }, 'roe', 'en'), '20.0%');
  assert.equal(peerMedianText({ peer_median: null }, 'roe', 'en'), 'No data');
  // castellano intacto
  assert.equal(formatPeerValue('0.1234', 'net_margin', 'es'), '12,3 %');
});
