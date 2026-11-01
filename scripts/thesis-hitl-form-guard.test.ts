import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const form = readFileSync('components/research/ThesisHumanInputForm.tsx', 'utf8');
const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');
const memo = readFileSync('components/research/ThesisMemo.tsx', 'utf8');

test('HITL form is connected to the thesis and explicitly saves assumptions', () => {
  assert.match(memo, /<ThesisHumanInputForm ticker=\{ticker\}/);
  for (const field of ['driver_key', 'fiscal_year', 'scenario', 'value', 'source', 'rationale']) {
    assert.ok(form.includes(`name="${field}"`));
  }
  assert.match(form, /t\('research\.thesisHumanInput\.saved'\)/);
  const saved: string = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).thesisHumanInput.saved;
  assert.match(saved, /no se ha convertido en un dato verificado/);
  assert.match(saved, /Regenera la tesis/);
  assert.match(form, /disabled=\{pending\}/);
});

test('HITL action validates finite values and never silently generates thesis', () => {
  const action = actions.slice(actions.indexOf('export async function submitThesisHumanInput'));
  assert.match(action, /Number\.isFinite/);
  assert.match(action, /Number\.isInteger/);
  assert.match(action, /\/inputs/);
  assert.match(action, /method: 'POST'/);
  assert.doesNotMatch(action, /startThesisJob|\/generate|postJson/);
});
