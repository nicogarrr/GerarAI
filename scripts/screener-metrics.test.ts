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


test('cobertura conocida vacía no equivale a proveedor desconocido', () => {
  assert.deepEqual(buildMetricOptions([]), []);
  assert.ok(buildMetricOptions(undefined).length > 20);
});

test('cobertura vacía conserva métricas personalizadas sin cambiar su escala', () => {
  const options = buildMetricOptions([], [{ metric_key: 'roic_spread', name: 'Diferencial ROIC', unit: 'percent' }]);
  assert.deepEqual(options.map((option: { key: string }) => option.key), ['roic_spread']);
  assert.equal(options[0].unit, 'number');
});


test('valoración, tesis y nivel DCA son métricas del screener con su unidad', () => {
  type Option = { key: string; unit: string; group: string };
  const options: Option[] = buildMetricOptions(['margen_seguridad', 'tiene_tesis', 'nivel_dca']);
  const byKey = new Map(options.map((o) => [o.key, o]));
  assert.equal(byKey.get('margen_seguridad')?.unit, 'ratio');
  assert.equal(byKey.get('nivel_dca')?.unit, 'number');
  assert.equal(byKey.get('tiene_tesis')?.group, 'Tesis y nivel DCA');
  // Margen del 20 % que escribe la persona -> 0.2 en el backend.
  assert.equal(toBackendValue('20', 'ratio'), '0.2');
  // Sin datos de DCA (motor aún no desplegado) no se ofrece el filtro.
  assert.equal(buildMetricOptions(['margen_seguridad']).some((o: { key: string }) => o.key === 'nivel_dca'), false);
});
