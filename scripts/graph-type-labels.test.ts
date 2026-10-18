import { readFileSync } from 'node:fs';
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

test('selected node detail translates the type too', () => {
 const source = readFileSync('components/knowledge-graph/KnowledgeGraphCanvas.tsx', 'utf8');
 assert.match(source, /graphNodeTypeLabel\(selectedNode.type\)/);
 assert.doesNotMatch(source, /\{selectedNode.type\}<\/Badge>/);
});

test('SEC refresh phase has a human label and unknown phases stay nontechnical', () => {
 const source = readFileSync('components/research/ThesisGenerateButton.tsx','utf8');
 assert.match(source, /refresh_sec: 'Actualizando financieros SEC'/);
 assert.doesNotMatch(source, /PHASE_LABELS\[job.current_phase\] \?\? job.current_phase/);
});
