import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (31-oct-2026, medido en prod a 390px): /research/news tardaba 5,9 s de
// LCP porque la página entera esperaba a getResearchNews antes de pintar.
const src = readFileSync('app/(root)/research/news/page.tsx', 'utf8');
// Feed extraído a NewsFeedSection (#4895): los awaits viven en el componente
// bajo Suspense; la página solo CREA la promesa y la pasa por props.
const section = readFileSync('app/(root)/research/news/NewsFeedSection.tsx', 'utf8');

test('una sola petición de contexto compartida (promesa sin await en la página)', () => {
  assert.match(src, /const tickerContextPromise = getTickerContext\(\);/);
  const page = src.slice(src.indexOf('export default async function ResearchNewsPage'));
  assert.ok(!page.includes('await getTickerContext('), 'la página no espera el contexto');
  assert.ok(!page.includes('await getResearchNews('), 'la página no espera el feed');
  assert.match(section, /tickerContextPromise: ReturnType<typeof getTickerContext>/, 'el componente recibe la promesa, no el resultado');
  assert.match(section, /await tickerContextPromise/);
  assert.match(section, /await getResearchNews\(/);
  const feedAwait = section.indexOf('await getResearchNews(');
  assert.ok(feedAwait > -1, 'el feed se espera dentro del componente');
  const ctxAwait = section.indexOf('const tickerContext = await tickerContextPromise');
  assert.ok(ctxAwait > feedAwait, 'contexto y feed se resuelven en paralelo: el await del contexto va después del feed');
  // Solo el carril «Para ti» puede esperar el contexto antes del feed (filtra
  // por cartera/watchlist); ningún otro await temprano serializa la página.
  const beforeFeed = section.slice(0, feedAwait).replace(/if \(lane === 'para-ti'\) \{[\s\S]*?\n  \}/, '');
  assert.ok(!beforeFeed.includes('await tickerContextPromise'), 'fuera de «Para ti» el contexto no se espera antes del feed');
});

test('cabecera pinta fuera de Suspense y el feed va detrás de skeleton', () => {
  assert.ok(src.indexOf('<PageHeader') > src.indexOf('export default async function ResearchNewsPage'), 'PageHeader está en la página');
  const page = src.slice(src.indexOf('export default async function ResearchNewsPage'));
  assert.ok(page.indexOf('<PageHeader') < page.indexOf('<Suspense fallback'), 'PageHeader antes del Suspense del feed');
  assert.match(page, /<Suspense fallback=\{<NewsLoadingSkeleton \/>\}>/);
  assert.match(page, /<NewsFeedSection lane=\{lane\} page=\{page\} ticker=\{ticker\} tickerContextPromise=\{tickerContextPromise\} \/>/);
});
