import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('biblioteca: borrado de documentos expuesto con confirmación, nunca silencioso', () => {
  const button = readFileSync('components/knowledge/DeleteDocumentButton.tsx', 'utf8');
  assert.ok(button.includes('window.confirm('), 'el borrado pide confirmación explícita');
  assert.ok(button.includes('no se puede deshacer'), 'la confirmación avisa de que es irreversible');
  assert.ok(button.includes('fragmentos y principios extraídos'), 'la confirmación declara la cascada');

  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  assert.ok(page.includes('DeleteDocumentButton'), 'la página expone el borrado');
  assert.ok(page.includes('documentId={document.id}'), 'cada documento puede borrarse');

  const action = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');
  assert.ok(action.includes("method: 'DELETE'"), 'usa el DELETE existente del backend');
  assert.ok(action.includes("revalidatePath('/knowledge')"), 'la vista se refresca tras borrar');
});

test('biblioteca: las colecciones vacías también se borran con confirmación, nunca en silencio', () => {
  const button = readFileSync('components/knowledge/DeleteCollectionButton.tsx', 'utf8');
  assert.ok(button.includes('window.confirm('), 'el borrado pide confirmación explícita');
  assert.ok(button.includes('no se puede deshacer'), 'la confirmación avisa de que es irreversible');

  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  assert.ok(page.includes('DeleteCollectionButton'), 'la página expone el borrado de colecciones');
  assert.ok(page.includes('count === 0'), 'solo las colecciones vacías ofrecen el botón');

  const action = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');
  assert.ok(action.includes('deleteKnowledgeCollection'), 'existe la server action');
  assert.ok(action.includes('/api/knowledge/collections/'), 'usa el DELETE del backend');

  const route = readFileSync('data-engine/app/api/routes/knowledge.py', 'utf8');
  assert.ok(route.includes('Knowledge collection is not empty'), 'el backend rechaza colecciones con documentos (409)');
});
