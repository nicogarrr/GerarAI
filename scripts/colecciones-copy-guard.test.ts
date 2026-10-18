import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('colecciones: plural correcto y separador nombre-contador', () => {
  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  assert.ok(page.includes("count === 1 ? 'documento' : 'documentos'"), 'el contador singulariza «1 documento»');
  assert.ok(page.includes('· {count}'), 'separador visible entre nombre y contador');
  assert.ok(!page.includes('length} documentos en esta vista'), 'no queda el plural fijo');
});
