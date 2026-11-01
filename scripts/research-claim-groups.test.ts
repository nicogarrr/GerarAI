import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { groupClaimsByVersion } from '../lib/research/claim-groups.ts';
test('claims retain all entries and remain distinct by persisted thesis id', () => {
  const groups = groupClaimsByVersion([{id: 1, thesis_version_id: 14}, {id: 2, thesis_version_id: 9}, {id: 3, thesis_version_id: 14}, {id: 4, thesis_version_id: null}], [{id: 14, version: 7}]);
  assert.equal(groups.length, 3);
  assert.equal(groups[0].label, 'Tesis v7');
  assert.deepEqual(groups[0].claims.map(c => c.id), [1,3]);
  assert.equal(groups[1].label, 'Tesis vinculada (ID 9, versión N/D)');
  assert.equal(groups[2].label, 'Sin versión de tesis vinculada');
  assert.equal(groups.reduce((sum, group) => sum + group.claims.length, 0), 4);
});

test('missing forecast or actual value cannot render a successful review status', () => {
  const panel = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
  const list = readFileSync('components/research/ExpectationsList.tsx', 'utf8');
  // El texto vive en el diccionario (i18n): una sola clave en el panel y la redacción en es.json.
  assert.equal((panel.match(/research\.expect\.noComparison/g) ?? []).length, 1);
  assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).expect.noComparison, 'Sin comparación: falta dato');
  assert.match(list, /research\.expect\.list\.naHelp/);
  assert.match(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).expect.list.naHelp, /N\/D significa que falta el dato esperado o real/);
  assert.match(panel, /review\.expected_value != null && review\.actual_value != null && Number\.isFinite\(review\.expected_value\) && Number\.isFinite\(review\.actual_value\)/);
  assert.match(panel, /status: comparable \? reviewStatusLabel\(review\.status, ti\) : ti\('research\.expect\.noComparison'\)/);
  assert.match(list, /<Badge variant="outline">\{r\.status\}<\/Badge>/);
  assert.match(list, /research\.expect\.list\.naHelp/);
  assert.match(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).expect.list.naHelp, /N\/D significa que falta el dato esperado o real/);
});
