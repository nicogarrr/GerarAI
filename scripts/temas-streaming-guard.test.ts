import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Perf (14-nov-2026, medido en prod a 390px): /temas esperaba el ranking, pero
// también todos los detalles de flujos, exposición y cuellos antes de devolver
// las tarjetas. Esas secciones ahora entran por Suspense propias.
const src = readFileSync('app/(root)/temas/page.tsx', 'utf8');

test('la cabecera pinta en el primer chunk (antes de cualquier Suspense)', () => {
  const page = src.slice(src.indexOf('export default async function TemasPage'));
  assert.ok(page.indexOf('<header') < page.indexOf('<Suspense fallback'), 'el header debe renderizarse antes del primer Suspense');
});

test('las peticiones independientes se disparan en paralelo', () => {
  for (const p of ['const themesPromise = getMarketThemes();', 'const bottlenecksPromise = getBottlenecks()', 'const flowIdsPromise = getMoneyFlowThemes();', 'const holdingsPromise = getFlowHoldings();']) {
    assert.ok(src.includes(p), p);
  }
  assert.ok(src.indexOf('const themesPromise') < src.indexOf('await themesPromise'));
});

test('solo el ranking de temas bloquea las tarjetas', () => {
  const body = src.slice(src.indexOf('async function TemasBody'), src.indexOf('export default async function TemasPage'));
  assert.match(body, /data = await themesPromise;/);
  assert.doesNotMatch(body, /await\s+bottlenecksPromise/);
  assert.doesNotMatch(body, /await\s+flowIdsPromise/);
  assert.doesNotMatch(body, /await\s+holdingsPromise/);
  assert.doesNotMatch(body, /Promise\.all\(flowIds\.map/);
});

test('refreshing=true vacío es «preparando», nunca «sin datos» definitivo', () => {
  assert.match(src, /if \(data\.refreshing === true && data\.themes\.length === 0\)/);
  assert.match(src, /return <MarketThemesRefreshing \/>;/);
  const component = readFileSync('app/(root)/temas/_components/MarketThemesRefreshing.tsx', 'utf8');
  assert.match(component, /const REFRESH_EVERY_MS = 15_000;/);
  assert.match(component, /setInterval\(\(\) => router\.refresh\(\), REFRESH_EVERY_MS\)/);
});

test('flujo, exposición y cuellos se resuelven por secciones Suspense', () => {
  for (const section of ['ThemeFlowSection', 'ThemeHoldingsSection', 'ThemeBottleneckSection']) {
    assert.ok(src.includes(`async function ${section}`), section);
    assert.ok(src.includes(`<${section}`), `${section} montada`);
  }
  assert.match(src, /<Suspense fallback=\{null\}>\s*<ThemeFlowSection/);
  assert.match(src, /<Suspense fallback=\{null\}>\s*<ThemeHoldingsSection/);
  assert.match(src, /<Suspense fallback=\{null\}>\s*<ThemeBottleneckSection/);
  assert.match(src, /const \[flowIds, holdings\] = await Promise\.all\(\[flowIdsPromise, holdingsPromise\]\)/);
  assert.match(src, /const flow = await getMoneyFlow\(themeId\)/);
  assert.match(src, /const bottlenecks = await bottlenecksPromise/);
});
