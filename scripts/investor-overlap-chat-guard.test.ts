import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path: string) => readFileSync(path, 'utf8');
test('solape has pagination, period and partial-data labels', () => {
  // Movidas a vistas de /ownership (Movimientos 13F) por decision de Nico, WhatsApp 2026-10-20 00:59.
  // El texto vive en es/ownership.json: solo se añade la sección de Solape.
  const page = read('app/(root)/ownership/_components/Overlap.tsx') + JSON.stringify(JSON.parse(read('lib/i18n/messages/es/ownership.json')).overlap);
  for (const text of ['Pagination', 'report_date', 'filing_date', 'Datos parciales', 'unresolved_positions', '13F histórico']) assert.ok(page.includes(text), text);
});
test('chat sends only signed server requests and renders quotes as plain text', () => {
  const action = read('lib/actions/knowledge-chat.actions.ts');
  assert.ok(action.includes('researchRequest<LibraryAnswer>'));
  assert.ok(action.includes("timeoutMs: mode === 'analisis' ? 90_000 : 60_000"));
  assert.ok(!action.includes('fetch('));
  assert.ok(action.includes("method: 'POST'"));
  const component = read('components/brain/BrainLibraryAnswer.tsx');
  assert.ok((read('components/brain/GlobalBrain.tsx') + read('components/brain/GlobalBrainPanel.tsx')).includes('brain.panel.doctrineNote'));
  const dictBrain = JSON.parse(readFileSync('lib/i18n/messages/es/brain.json', 'utf8'));
  assert.ok(dictBrain.panel.doctrineNote.startsWith('Doctrina, no datos actuales'), dictBrain.panel.doctrineNote);
  assert.ok(component.includes('{point.citation.quote}') && component.includes('{answer.citation.quote}'));
  // B4: sin «Página/Fecha no registrada»: el dato que falta se omite, nunca se inventa.
  assert.ok(!component.includes('Página no registrada') && !component.includes('Fecha no registrada'));
  assert.ok(component.includes('if (cite.page_number !== null)') && component.includes('if (cite.publication_date)'));

  assert.ok(!component.includes('dangerouslySetInnerHTML'));
  assert.ok(component.includes('chunk-${cite.chunk_id}'));
});
test('links from both library and letters and static route precedes slug route', () => {
  assert.ok(read('app/(root)/knowledge/page.tsx').includes('<LibraryChat scope="library"'));
  assert.ok(read('app/(root)/inversores/cartas/page.tsx').includes('<LibraryChat authors='));
  assert.ok(read('app/(root)/inversores/cartas/[id]/page.tsx').includes('id={`chunk-${chunk.id}`}'));
  const router = read('data-engine/app/api/routes/investors.py');
  assert.ok(router.indexOf('/portfolio-overlap') < router.indexOf('/{slug}'));
});
