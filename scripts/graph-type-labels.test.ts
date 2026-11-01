import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Node strip types requires explicit TS extension.
import { buildScene, describeDetail, graphNodeTypeLabel } from '../lib/knowledge-graph/graph-model.ts';
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
 // Las etiquetas de fase viven en lib/research/thesis-progress.ts (es y en); el botón las pide ahí.
 const progress = readFileSync('lib/research/thesis-progress.ts','utf8');
 assert.match(progress, /refresh_sec: 'Actualizando financieros SEC'/);
 assert.match(progress, /refresh_sec: 'Updating SEC financials'/);
 assert.match(source, /thesisPhaseLabel\(job.current_phase, locale\)/);
 assert.doesNotMatch(source, /PHASE_LABELS\[job.current_phase\] \?\? job.current_phase/);
 assert.match(progress, /\?\? 'Análisis en curso'/);
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

test('describeDetail absent reasons follow the locale and keep the historical ES literal', () => {
  const es = JSON.parse(readFileSync('lib/i18n/messages/es/knowledgeGraph.json', 'utf8')).detail.absentReason;
  const en = JSON.parse(readFileSync('lib/i18n/messages/en/knowledgeGraph.json', 'utf8')).detail.absentReason;
  const scene = buildScene({ nodes: [{ id: 1, key: '', type: 'author', label: 'X', description: '', company_id: null, entity_type: null, entity_id: null, confidence: '', attributes: {} }], edges: [], node_count: 1, edge_count: 0 } as never);
  const lookup = (d: Record<string, string>) => (key: string) => d[key.replace('knowledgeGraph.detail.absentReason.', '')];
  const plain = describeDetail(scene, 1).filter((f) => f.absent);
  assert.ok(plain.length >= 5);
  assert.equal(plain.find((f) => f.key === 'entityType')?.absent, 'Este nodo no esta enlazado con una entidad de otra tabla.');
  assert.equal(describeDetail(scene, 1, lookup(es) as never).filter((f) => f.absent).map((f) => f.absent).join('|'), plain.map((f) => f.absent).join('|'));
  const enReasons = describeDetail(scene, 1, lookup(en) as never).filter((f) => f.absent);
  assert.equal(enReasons.length, plain.length);
  enReasons.forEach((f, i) => assert.notEqual(f.absent, plain[i].absent));
  assert.equal(enReasons.find((f) => f.key === 'entityType')?.absent, 'This node is not linked to an entity in another table.');
  const canvas = readFileSync('components/knowledge-graph/KnowledgeGraphCanvas.tsx', 'utf8');
  assert.match(canvas, /describeDetail\(scene, selectedId, t\)/);
});
