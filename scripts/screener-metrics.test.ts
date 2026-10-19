import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { buildMetricOptions, fromBackendValue, toBackendValue } from '../lib/screener-metrics.ts';

test('solo ofrece métricas con datos, agrupadas, y añade las personalizadas', () => {
  const options = buildMetricOptions(['roic', 'market_cap', 'metrica_rara'], [{ metric_key: 'roic_spread', name: 'Diferencial ROIC', unit: 'percent' }]);
  assert.deepEqual(options.map((o: { key: string }) => o.key), ['roic', 'market_cap', 'roic_spread', 'metrica_rara']);
  assert.equal(options.find((o: { key: string }) => o.key === 'roic')?.group, 'Rentabilidad');
  assert.equal(options.find((o: { key: string }) => o.key === 'roic_spread')?.unit, 'number');
  assert.equal(options.find((o: { key: string }) => o.key === 'metrica_rara')?.group, 'Otras');
});

test('sin cobertura ofrece el catálogo completo', () => {
  assert.ok(buildMetricOptions(undefined).length > 20);
});

test('convierte lo que ve la persona al valor del backend y de vuelta', () => {
  assert.equal(toBackendValue('15', 'ratio'), '0.15');
  assert.equal(toBackendValue('15,5', 'ratio'), '0.155');
  assert.equal(toBackendValue('500', 'usd'), '500000000');
  assert.equal(toBackendValue('', 'ratio'), '');
  assert.equal(fromBackendValue('0.15', 'ratio'), '15');
  assert.equal(fromBackendValue('abc', 'ratio'), '');
});
