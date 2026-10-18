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
  assert.ok(button.includes('también los ya aprobados'), 'la confirmación declara que los principios aprobados también se eliminan');
  assert.ok(button.includes('archivo original sigue en el almacén'), 'la confirmación declara que el archivo original se conserva');
  assert.ok(page.includes('documentId={document.id}'), 'cada documento puede borrarse');

  const action = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');
  assert.ok(action.includes("method: 'DELETE'"), 'usa el DELETE existente del backend');
  assert.ok(action.includes("revalidatePath('/knowledge')"), 'la vista se refresca tras borrar');
});
