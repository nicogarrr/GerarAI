import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('biblioteca: borrado de documentos expuesto con confirmación, nunca silencioso', () => {
  // Documento: wrapper (identidad + claves i18n) + impl compartida (confirmacion y mutacion).
  const button = readFileSync('components/knowledge/DeleteDocumentButton.tsx', 'utf8') + '\n' + readFileSync('components/knowledge/DeleteKnowledgeButton.tsx', 'utf8') + '\n' + Object.values(JSON.parse(readFileSync('lib/i18n/messages/es/knowledge.json', 'utf8')).delete).join('\n');
  assert.ok(button.includes('<ConfirmDialog'), 'el borrado pide confirmación explícita con el diálogo compartido');
  assert.ok(button.includes('onConfirm={handleDelete}'), 'la mutación solo se ejecuta al confirmar');
  assert.ok(!button.includes('onClick={handleDelete}'), 'ningún click borra sin confirmar');
  assert.ok(/t\('knowledge\.delete\.confirm(Collection)?Description'\)/.test(button) && Object.values(JSON.parse(readFileSync('lib/i18n/messages/es/knowledge.json', 'utf8')).delete).some((v) => String(v).includes('no se puede deshacer')), 'la confirmación avisa de que es irreversible');
  assert.ok(button.includes('fragmentos y principios extraídos'), 'la confirmación declara la cascada');

  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  assert.ok(page.includes('DeleteDocumentButton'), 'la página expone el borrado');
  assert.ok(button.includes('también los ya aprobados'), 'la confirmación declara que los principios aprobados también se eliminan');
  assert.ok(button.includes('archivo original sigue en el almacén'), 'la confirmación declara que el archivo original se conserva');
  assert.ok(page.includes('documentId={document.id}'), 'cada documento puede borrarse');

  const action = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');
  assert.ok(action.includes("method: 'DELETE'"), 'usa el DELETE existente del backend');
  assert.ok(action.includes("revalidatePath('/knowledge')"), 'la vista se refresca tras borrar');
});

test('biblioteca: las colecciones vacías también se borran con confirmación, nunca en silencio', () => {
  // Coleccion: wrapper (identidad + claves i18n) + impl compartida (confirmacion y mutacion).
  const button = readFileSync('components/knowledge/DeleteCollectionButton.tsx', 'utf8') + '\n' + readFileSync('components/knowledge/DeleteKnowledgeButton.tsx', 'utf8') + '\n' + Object.values(JSON.parse(readFileSync('lib/i18n/messages/es/knowledge.json', 'utf8')).delete).join('\n');
  assert.ok(button.includes('<ConfirmDialog'), 'el borrado pide confirmación explícita con el diálogo compartido');
  assert.ok(button.includes('onConfirm={handleDelete}'), 'la mutación solo se ejecuta al confirmar');
  assert.ok(!button.includes('onClick={handleDelete}'), 'ningún click borra sin confirmar');
  assert.ok(/t\('knowledge\.delete\.confirm(Collection)?Description'\)/.test(button) && Object.values(JSON.parse(readFileSync('lib/i18n/messages/es/knowledge.json', 'utf8')).delete).some((v) => String(v).includes('no se puede deshacer')), 'la confirmación avisa de que es irreversible');

  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  assert.ok(page.includes('DeleteCollectionButton'), 'la página expone el borrado de colecciones');
  assert.ok(page.includes('count === 0'), 'solo las colecciones vacías ofrecen el botón');

  const action = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');
  assert.ok(action.includes('deleteKnowledgeCollection'), 'existe la server action');
  assert.ok(action.includes('/api/knowledge/collections/'), 'usa el DELETE del backend');

  const route = readFileSync('data-engine/app/api/routes/knowledge.py', 'utf8');
  assert.ok(route.includes('Knowledge collection is not empty'), 'el backend rechaza colecciones con documentos (409)');
});

test('biblioteca: la lógica de borrado vive UNA vez en DeleteKnowledgeButton', () => {
  const impl = readFileSync('components/knowledge/DeleteKnowledgeButton.tsx', 'utf8');
  const doc = readFileSync('components/knowledge/DeleteDocumentButton.tsx', 'utf8');
  const col = readFileSync('components/knowledge/DeleteCollectionButton.tsx', 'utf8');
  assert.ok(doc.includes('<DeleteKnowledgeButton'), 'el botón de documento usa la impl compartida');
  assert.ok(col.includes('<DeleteKnowledgeButton'), 'el botón de colección usa la impl compartida');
  assert.ok(!doc.includes('useState') && !col.includes('useState'), 'ningún wrapper repite la máquina de estados');
  assert.ok(impl.includes('onConfirm={handleDelete}'), 'la mutación solo se ejecuta al confirmar');
  assert.ok(!impl.includes('onClick={handleDelete}'), 'ningún click borra sin confirmar');
});
