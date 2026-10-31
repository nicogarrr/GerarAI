import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// La ficha de empresa ya no pinta respuestas de chat propio.
test('la ficha no pinta respuestas de chat', () => {
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.ok(!page.includes('response.sources'));
});
