import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const src = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');

test('con 0 aptas el boton vuelve a ejecutar el embudo, no solo relee el run', () => {
  assert.ok(src.includes('onClick={lastGenerated && passedCount !== 0 ? handleRefresh : handleGenerateRun}'));
});

test('el estado vacio con 0 aptas explica la causa accionable', () => {
  assert.ok(src.includes('ejecuta la selección de nuevo para evaluar las empresas con los datos de mercado actuales'));
});
