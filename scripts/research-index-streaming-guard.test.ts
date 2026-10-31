import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (31-oct-2026, medido en prod a 390px): /research tardaba 3,6 s de LCP
// (5,8 s con redirección del assistant) porque la página entera esperaba al
// dashboard y a los snapshots antes de pintar cabecera y Panel.
const src = readFileSync('app/(root)/research/page.tsx', 'utf8');

test('la página no espera datos: el índice va en una sección async hija', () => {
  const page = src.slice(src.indexOf('export default async function ResearchPage'));
  assert.ok(!page.includes('await getResearchDashboard('), 'la página no espera el dashboard');
  assert.ok(!page.includes('await getResearchCompanySnapshots('), 'la página no espera los snapshots');
  const section = src.slice(src.indexOf('async function ResearchIndexSection'));
  assert.match(section, /await getResearchDashboard\(/);
  assert.match(section, /await fetchInBatches\(/);
});

test('cabecera y Panel fuera de Suspense con skeleton de tarjetas', () => {
  const page = src.slice(src.indexOf('export default async function ResearchPage'));
  assert.ok(page.indexOf('<PageHeader') < page.indexOf('<Suspense fallback'), 'PageHeader antes del Suspense');
  assert.match(page, /<Suspense fallback=\{<ResearchIndexSkeleton \/>\}>/);
  assert.match(page, /<ResearchIndexSection query=\{query\} requestedPage=\{requestedPage\} \/>/);
  assert.ok(page.indexOf("title={t('research.registryTitle')}") < page.indexOf('<Suspense fallback'), 'Panel antes del Suspense');
});

test('BackendOffline sigue inline dentro de la sección', () => {
  const section = src.slice(src.indexOf('async function ResearchIndexSection'));
  assert.match(section, /if \(isBackendUnavailableError\(error\)\)/);
  assert.match(section, /<BackendOffline/);
});
