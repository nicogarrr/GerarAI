import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('colecciones: plural correcto y separador nombre-contador', () => {
  const page = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
  const esK = JSON.parse(readFileSync('lib/i18n/messages/es/knowledge.json', 'utf8'));
  assert.ok(page.includes("count === 1 ? t('knowledge.documentsCount.one', { count }) : t('knowledge.documentsCount.other', { count })"), 'el contador singulariza «1 documento»');
  assert.equal(esK.documentsCount.one, '{count} documento');
  assert.equal(esK.documentsCount.other, '{count} documentos');
  assert.ok(page.includes('· {count === 1 ? t('), 'separador visible entre nombre y contador');
  assert.ok(!page.includes('length} documentos en esta vista'), 'no queda el plural fijo');
});
