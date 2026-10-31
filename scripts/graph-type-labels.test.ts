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
 assert.match(source, /graphNodeTypeLabel\(selectedNode.type, t\)/);
 assert.doesNotMatch(source, /\{selectedNode.type\}<\/Badge>/);
});

test('SEC refresh phase has a human label and unknown phases stay nontechnical', () => {
 const source = readFileSync('components/research/ThesisGenerateButton.tsx','utf8');
 assert.match(source, /refresh_sec: 'Actualizando financieros SEC'/);
 assert.doesNotMatch(source, /PHASE_LABELS\[job.current_phase\] \?\? job.current_phase/);
});

test('node type labels follow the active locale through knowledgeGraph.nodeType.* keys', () => {
  const es = JSON.parse(readFileSync('lib/i18n/messages/es/knowledgeGraph.json', 'utf8')).nodeType;
  const en = JSON.parse(readFileSync('lib/i18n/messages/en/knowledgeGraph.json', 'utf8')).nodeType;
  const camel = (k: string) => k.replace(/_(\w)/g, (_m, c: string) => c.toUpperCase());
  const lookup = (d: Record<string, string>) => (key: string) => d[key.replace('knowledgeGraph.nodeType.', '')];
  for (const type of ['company', 'principle', 'author', 'decision', 'decision_lesson', 'kpi', 'risk', 'concept', 'case_study']) {
    assert.equal(graphNodeTypeLabel(type.toUpperCase(), lookup(es) as never), graphNodeTypeLabel(type));
    assert.ok(en[camel(type)] && en[camel(type)] !== es[camel(type)], `EN label for ${type}`);
    assert.equal(graphNodeTypeLabel(type, lookup(en) as never), en[camel(type)]);
  }
  assert.equal(graphNodeTypeLabel('new_type', lookup(en) as never), 'new type');
});

test('KnowledgeGraphCanvas uses the locale-aware useT and passes t to every type label', () => {
  const source = readFileSync('components/knowledge-graph/KnowledgeGraphCanvas.tsx', 'utf8');
  assert.match(source, /import \{ useT \} from '@\/lib\/i18n\/client'/);
  assert.doesNotMatch(source, /from '@\/lib\/i18n\/t'/);
  assert.match(source, /const t = useT\(\);/);
  assert.doesNotMatch(source, /graphNodeTypeLabel\([\w.]+\)/);
  const page = readFileSync('app/(root)/knowledge-graph/page.tsx', 'utf8');
  assert.doesNotMatch(page, /graphNodeTypeLabel\(\w+\)/);
});
