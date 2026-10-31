import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (31-oct-2026, medido en prod a 390px): /research/news tardaba 5,9 s de
// LCP porque la página entera esperaba a getResearchNews antes de pintar.
const src = readFileSync('app/(root)/research/news/page.tsx', 'utf8');

test('una sola petición de contexto compartida (promesa sin await en la página)', () => {
  assert.match(src, /const tickerContextPromise = getTickerContext\(\);/);
  const page = src.slice(src.indexOf('export default async function ResearchNewsPage'));
  assert.ok(!page.includes('await getTickerContext('), 'la página no espera el contexto');
  assert.ok(!page.includes('await getResearchNews('), 'la página no espera el feed');
  assert.match(src, /await tickerContextPromise/);
  assert.match(src, /await getResearchNews\(/);
});

test('cabecera pinta fuera de Suspense y el feed va detrás de skeleton', () => {
  assert.ok(src.indexOf('<PageHeader') > src.indexOf('export default async function ResearchNewsPage'), 'PageHeader está en la página');
  const page = src.slice(src.indexOf('export default async function ResearchNewsPage'));
  assert.ok(page.indexOf('<PageHeader') < page.indexOf('<Suspense fallback'), 'PageHeader antes del Suspense del feed');
  assert.match(page, /<Suspense fallback=\{<NewsLoadingSkeleton \/>\}>/);
  assert.match(page, /<NewsFeedSection lane=\{lane\} page=\{page\} ticker=\{ticker\} tickerContextPromise=\{tickerContextPromise\} \/>/);
});
