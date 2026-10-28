import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
const client = readFileSync('lib/research/assistant-client.ts', 'utf8');
const contract = readFileSync('lib/research/assistant-contract.ts', 'utf8');
const openBrain = readFileSync('lib/brain/open-brain.ts', 'utf8');
const actions = readFileSync('lib/actions/brain.actions.ts', 'utf8');
const history = readFileSync('lib/brain/history.ts', 'utf8');
const route = readFileSync('data-engine/app/api/routes/research_assistant.py', 'utf8');

test('el modo guia del Cerebro envia contexto de pagina e historial', () => {
  const guide = brain.slice(brain.indexOf('askResearchAssistantAction({'), brain.indexOf('} catch', brain.indexOf('askResearchAssistantAction({')));
  assert.match(guide, /\bpage,/);
  assert.match(guide, /\bhistory,/);
  assert.match(guide, /setEcho\(result\.context\)/);
});

test('el cliente del asistente reenvia page e historial acotado', () => {
  assert.match(contract, /page\?: BrainPageContext \| null/);
  assert.match(contract, /history\?: BrainHistoryTurn\[\]/);
  assert.match(client, /page: request\.page/);
  assert.match(client, /history: trimBrainHistory\(request\.history\)/);
});

test('el recorte de historial es una sola funcion compartida', () => {
  assert.match(history, /export function trimBrainHistory/);
  assert.match(actions, /import \{ trimBrainHistory/);
  assert.doesNotMatch(actions, /function trimBrainHistory/);
});

test('el backend del asistente acepta history', () => {
  assert.match(route, /history: list\[ChatTurn\]/);
});

test('openBrain: evento si el Cerebro esta montado, handoff si no, nunca ambos', () => {
  assert.match(openBrain, /export function openBrain/);
  assert.match(openBrain, /hasAttribute\(READY_ATTR\)/);
  assert.match(brain, /markBrainReady\(true\)/);
  assert.match(brain, /markBrainReady\(false\)/);
});
