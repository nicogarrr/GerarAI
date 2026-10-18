import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('data health and public shorts expose honest dates, provenance and pagination', () => {
  const health = fs.readFileSync('app/(root)/research/data-health/page.tsx', 'utf8');
  const shorts = fs.readFileSync('app/(root)/research/[ticker]/shorts/page.tsx', 'utf8');
  assert.match(health, /coverage_pct === null/);
  assert.match(health, /Última escritura/);
  assert.match(health, /Páginas de fuentes de noticias/);
  assert.match(health, /Páginas de consultas/);
  assert.match(shorts, /Fecha de posición/);
  assert.match(shorts, /Fecha de negociación/);
  assert.match(shorts, /DERIVADO/);
  assert.match(shorts, /Sin notificaciones/);
  assert.doesNotMatch(shorts, /public_total_percent \?\? 0/);
  assert.match(shorts, /Páginas de posiciones/);
});
