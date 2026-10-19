import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: ejecución directa con Node.
import { collapseVersionHistory } from '../lib/research/version-history.ts';

const entry = (version: number, summary: string | null, status = 'published', rating = 'buy') => ({
  version,
  status,
  rating,
  diff: summary === null ? null : { change_summary: summary, affected_assumptions: [], rating_changed: false, created_at: '' },
});

test('colapsa versiones seguidas con el mismo resumen', () => {
  const groups = collapseVersionHistory([
    entry(25, 'Sin cambios materiales (±0,5 %) en calificación.'),
    entry(24, 'Sin cambios materiales (±0,5 %) en calificación.'),
    entry(23, 'Sin cambios materiales (±0,5 %) en calificación.'),
    entry(22, 'Sube el escenario alcista por el acuerdo.'),
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].map((e) => e.version), [25, 24, 23]);
  assert.deepEqual(groups[1].map((e) => e.version), [22]);
});

test('no colapsa si cambia el estado o el rating aunque el resumen coincida', () => {
  const groups = collapseVersionHistory([
    entry(25, 'Mismo resumen', 'draft', 'buy'),
    entry(24, 'Mismo resumen', 'published', 'buy'),
    entry(23, 'Mismo resumen', 'published', 'hold'),
  ]);
  assert.equal(groups.length, 3);
});

test('no colapsa entradas sin resumen', () => {
  const groups = collapseVersionHistory([entry(25, null), entry(24, null)]);
  assert.equal(groups.length, 2);
});
