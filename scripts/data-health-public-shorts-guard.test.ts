import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// /research/data-health se eliminó entera por decisión de Nico (2026-10-20);
// las posiciones cortas públicas (/research/[ticker]/shorts) se conservan.
test('public shorts expose honest dates, provenance and pagination', () => {
  const shorts = fs.readFileSync('app/(root)/research/[ticker]/shorts/page.tsx', 'utf8');
  assert.match(shorts, /Fecha de posición/);
  assert.match(shorts, /Fecha de negociación/);
  assert.match(shorts, /DERIVADO/);
  assert.match(shorts, /Sin notificaciones/);
  assert.doesNotMatch(shorts, /public_total_percent \?\? 0/);
  assert.match(shorts, /Páginas de posiciones/);
});
