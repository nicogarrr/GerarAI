// Guard: la página de filtro guardado explica el 0 por falta de dato
// (roic >= wacc sin cobertura de wacc) en vez de mostrar solo «0 coincidencias».
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const SRC = readFileSync('app/(root)/screeners/[screenId]/page.tsx', 'utf8');
const RESULTS_SRC = readFileSync('lib/screener-results.ts', 'utf8');

test('aviso de métricas sin dato en ninguna empresa', () => {
  assert.match(SRC, /metrics_without_data/);
  assert.match(SRC, /Ninguna empresa tiene dato de:/);
});

test('agrega missing_fields de criterios y los muestra con frecuencia', () => {
  assert.match(SRC, /criterion\.missing_fields/);
  assert.match(SRC, /Sin coincidencias por falta de dato, no por incumplimiento/);
  // La composición de cada entrada vive en lib/screener-results.ts
  // (screenMissingDataEntry): la página la usa y el helper lleva el literal.
  assert.match(SRC, /screenMissingDataEntry/);
  assert.match(RESULTS_SRC, /sin dato en /);
});

test('cada métrica del aviso va con etiqueta legible, no con el slug crudo', () => {
  assert.match(RESULTS_SRC, /metricLabel\(field\)/);
});

test('el aviso es honesto: no inventa el dato', () => {
  assert.match(SRC, /El filtro no inventa el dato que falta/);
  assert.match(SRC, /role="alert"/);
});
