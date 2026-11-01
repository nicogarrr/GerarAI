import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// /research/data-health se eliminó entera por decisión de Nico (2026-10-20);
// las posiciones cortas públicas (/research/[ticker]/shorts) se conservan.
test('public shorts expose honest dates, provenance and pagination', () => {
  const shorts = fs.readFileSync('app/(root)/research/[ticker]/shorts/page.tsx', 'utf8');
  // Los textos viven en research.publicShorts.* (es y en); la página los pide por clave.
  const es = JSON.parse(fs.readFileSync('lib/i18n/messages/es/research.json', 'utf8')).publicShorts;
  assert.match(es.positionDate, /Fecha de posición/);
  assert.match(es.tradeDate, /Fecha de negociación/);
  assert.equal(es.derived, 'DERIVADO');
  assert.match(es.noNotifications, /Sin notificaciones/);
  for (const key of ['positionDate', 'tradeDate', 'derived', 'noNotifications']) assert.match(shorts, new RegExp(`research\\.publicShorts\\.${key}`));
  assert.doesNotMatch(shorts, /public_total_percent \?\? 0/);
  assert.equal(es.pagesLabel, 'Páginas de posiciones');
  assert.match(shorts, /research\.publicShorts\.pagesLabel/);
});
