/**
 * Botón de borrado de documentos en /knowledge: antes solo había
 * «Fragmentos» y «Extraer»; un documento subido por error no se podía
 * quitar. Ahora: botón Borrar con confirmación propia en dos pasos (nada
 * de confirm() nativo) que avisa de la cascada (fragmentos y principios),
 * contra el DELETE del backend.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/knowledge-delete-button-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const button = readFileSync('components/knowledge/KnowledgeDeleteButton.tsx', 'utf8');
const actions = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');

describe('knowledge delete button guard', () => {
  it('la tabla y las tarjetas ofrecen Borrar', () => {
    const placements = page.split('KnowledgeDeleteButton documentId={document.id}').length - 1;
    assert.ok(placements >= 2, 'borrado en tabla y en tarjetas');
  });

  it('confirmación propia en dos pasos, sin confirm() nativo', () => {
    assert.ok(!button.includes('window.confirm'), 'sin confirm() nativo');
    assert.match(button, /setConfirming\(true\)/);
    assert.match(button, /Sí, borrar/);
    assert.match(button, /Cancelar/);
    assert.match(button, /fragmentos y los principios/, 'avisa de la cascada');
  });

  it('la acción llama al DELETE del backend y revalida', () => {
    assert.match(actions, /deleteKnowledgeDocument[\s\S]*?method: 'DELETE'/);
    assert.match(actions, /deleteKnowledgeDocument[\s\S]*?revalidatePath\('\/knowledge'\)/);
  });
});
