import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (31-oct-2026, medido en prod a 390px): /screeners tardaba 15,5 s de LCP
// porque el page hacía await de workspace + cobertura antes de pintar nada.
// La cabecera debe quedar fuera de los <Suspense> y las dos peticiones se
// disparan en paralelo.
const src = readFileSync('app/(root)/screeners/page.tsx', 'utf8') + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/screener.json', 'utf8')).screens);

test('la cabecera pinta en el primer chunk (antes de cualquier Suspense)', () => {
  assert.ok(src.indexOf('<header') < src.indexOf('<Suspense fallback'), 'el header debe renderizarse antes del primer Suspense');
});

test('workspace y cobertura se piden en paralelo dentro de una sección en Suspense', () => {
  assert.match(src, /const workspacePromise = getScreenerWorkspace\(\);/);
  assert.match(src, /const coveragePromise = getScreenerMetricCoverage\(\);/);
  assert.ok(src.indexOf('const workspacePromise') < src.indexOf('await workspacePromise'));
  assert.match(src, /await coveragePromise;/);
  assert.match(src, /<Suspense fallback=\{<ScreenersBodySkeleton \/>\}>/);
});

test('los resultados ad-hoc llegan por streaming solo cuando hay ejecución intentada', () => {
  assert.match(src, /\{attemptedRun && !incompleteRun \? \(\s*<Suspense fallback=\{null\}>/);
});
