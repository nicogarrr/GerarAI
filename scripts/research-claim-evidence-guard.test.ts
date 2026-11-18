/**
 * Guard del hallazgo P1: la ficha tiene que seguir cableando la evidencia que
 * el backend ya devuelve. El test de comportamiento (tests/unit/components/
 * ClaimEvidenceList.test.tsx) comprueba QUÉ pinta el componente; este guard
 * comprueba el cableado de la página, que no se puede renderizar en Vitest sin
 * levantar todo el workspace de la ficha.
 *
 * Ejecución: node --experimental-strip-types --test scripts/research-claim-evidence-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const readSource = (rel: string) => readFileSync(join(root, rel), 'utf8');

describe('ficha: cableado de evidencia de afirmaciones', () => {
  it('la acción expone los campos de la cadena que la ficha necesita', () => {
    const actions = readSource('lib/actions/research.actions.ts');
    assert.ok(actions.includes('export type ResearchClaimEvidence'), 'el tipo de evidencia es reutilizable');
    for (const field of ['document_id', 'document_chunk_id', 'source_url', 'source_tier', 'confidence']) {
      assert.ok(actions.includes(`${field}:`), `ResearchClaimEvidence expone ${field}`);
    }
  });

  it('la ficha pasa la evidencia de cada afirmación al componente', () => {
    const page = readSource('app/(root)/research/[ticker]/page.tsx');
    assert.ok(page.includes("from '@/components/research/ClaimEvidenceList'"), 'importa el componente');
    assert.ok(page.includes('<ClaimEvidenceList evidence={claim.evidence}'), 'pinta la evidencia persistida');
    assert.ok(!/^function safeHttpUrl\(/m.test(page), 'safeHttpUrl tiene una sola definición, compartida');
  });
});
