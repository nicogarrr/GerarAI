import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (31-oct-2026, medido en prod a 390px): /temas tardaba 7,3 s de LCP por
// awaits secuenciales (temas -> cuellos -> flujos) antes de pintar nada.
const src = readFileSync('app/(root)/temas/page.tsx', 'utf8');

test('la cabecera pinta en el primer chunk (antes de cualquier Suspense)', () => {
  assert.ok(src.indexOf('<header') < src.indexOf('<Suspense fallback'), 'el header debe renderizarse antes del primer Suspense');
});

test('las peticiones independientes se disparan en paralelo', () => {
  for (const p of ['const themesPromise = getMarketThemes();', 'const bottlenecksPromise = getBottlenecks()', 'const flowIdsPromise = getMoneyFlowThemes();', 'const holdingsPromise = getFlowHoldings();']) {
    assert.ok(src.includes(p), p);
  }
  assert.ok(src.indexOf('const themesPromise') < src.indexOf('await themesPromise'));
  assert.match(src, /await bottlenecksPromise;/);
  assert.match(src, /await flowIdsPromise;/);
  assert.match(src, /holdingsPromise,/);
});
