import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Cached balances remain user-scoped, labelled and written only on success.
const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
const cache = readFileSync('lib/home/portfolio-cache.ts', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/home.json', 'utf8'));

test('la clave de caché va por usuario (invalidación al cambiar de cuenta)', () => {
  assert.match(cache, /gerarai:home-portfolio:\$\{/);
  assert.match(src, /readCachedPortfolio\(userId\)/);
});

test('solo se cachea un fetch OK: el fallo nunca pisa el último dato bueno', () => {
  const writeIdx = src.indexOf('writeCachedPortfolio(');
  assert.ok(writeIdx > 0, 'debe escribirse caché al llegar el dato fresco');
  // La escritura va DENTRO de la rama sin error.
  const before = src.slice(Math.max(0, writeIdx - 420), writeIdx);
  assert.match(before, /!result\.error|result\.error === null/, 'writeCachedPortfolio debe estar bajo guarda de éxito');
});

test('el dato cacheado se muestra SIEMPRE con su marca de «guardado de …»', () => {
  assert.match(src, /portfolioStaleAt/);
  assert.match(src, /t\('home\.portfolio\.cachedAt'/);
  // La marca solo desaparece cuando llega el dato real.
  assert.match(src, /setPortfolioStaleAt\(null\)/);
  assert.ok(es.portfolio.cachedAt?.includes('{time}'), 'falta home.portfolio.cachedAt en es');
  assert.ok(en.portfolio.cachedAt?.includes('{time}'), 'falta home.portfolio.cachedAt en en');
});
