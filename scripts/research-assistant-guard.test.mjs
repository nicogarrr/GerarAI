import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safeAssistantSourceUrl } from '../lib/research/assistant-contract.ts';

const ui = readFileSync(new URL('../components/brain/BrainGuideAnswer.tsx', import.meta.url), 'utf8');
const client = readFileSync(new URL('../lib/research/assistant-client.ts', import.meta.url), 'utf8');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/research-assistant.json', import.meta.url), 'utf8'));

test('contrato fixture: evidencia insuficiente sin writeback', () => {
  assert.equal(fixture.mode, 'guide');
  assert.equal(fixture.status, 'insufficient_data');
  assert.equal(fixture.writeback, false);
  assert.equal(fixture.citations.find((citation) => citation.kind === 'news_event').as_of, null);
  assert.deepEqual(fixture.missing_data, ['Periodo comparable']);
});
test('fuentes solo enlazables si son http(s) seguros', () => {
  assert.equal(safeAssistantSourceUrl(fixture.citations[0].url), 'https://example.org/report');
  for (const url of ['javascript:alert(1)', 'data:text/html,hi', '/relative', 'https://user:pass@example.org', 'http://']) {
    assert.equal(safeAssistantSourceUrl(url), null, url);
  }
});
test('la interfaz usa el nuevo endpoint y no ofrece aceptar tickets', () => {
  assert.match(client, /researchRequest<AssistantResponse>\('\/api\/research\/assistant'/);
  assert.doesNotMatch(client, /['"]\/api\/chat['"]/);
  assert.match(ui, /Noticia atribuida/);
  assert.match(ui, /Datos insuficientes/);
  assert.match(ui, /Sin escritura/);
  assert.doesNotMatch(ui, /acceptReview|approveReview|aceptar conclusión/i);
});
