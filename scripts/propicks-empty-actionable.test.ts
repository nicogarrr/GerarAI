import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

const src = (readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8') + ES_PROPICKS_JSON);

test('con 0 aptas el boton vuelve a ejecutar el embudo, no solo relee el run', () => {
  assert.ok(src.includes('const emptyStateNeedsRun = !lastGenerated || passedCount === 0;'));
  assert.ok(src.includes('onClick={emptyStateNeedsRun ? handleGenerateRun : handleRefresh}'));
});

test('el estado vacio con 0 aptas explica la causa accionable', () => {
  assert.ok(src.includes('ejecuta la selección de nuevo para evaluar las empresas con los datos de mercado actuales'));
});
