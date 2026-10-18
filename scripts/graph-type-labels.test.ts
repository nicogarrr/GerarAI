import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Node strip types requires explicit TS extension.
import { graphNodeTypeLabel } from '../lib/knowledge-graph/graph-model.ts';
test('graph types have Spanish display labels without changing their keys', () => {
  assert.equal(graphNodeTypeLabel('COMPANY'), 'Empresa');
  assert.equal(graphNodeTypeLabel('company'), 'Empresa');
  assert.equal(graphNodeTypeLabel('decision_lesson'), 'Lección');
  assert.equal(graphNodeTypeLabel('new_type'), 'new type');
});
