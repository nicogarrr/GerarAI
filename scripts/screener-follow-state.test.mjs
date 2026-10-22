import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const page = readFileSync('app/(root)/screener/page.tsx', 'utf8');
test('Mercado consulta pertenencia real sin degradarla a watchlist vacía', () => {
  assert.match(page, /getWatchlistState\(\)/);
  assert.match(page, /engineScreens, watchlist\] = await Promise\.all/);
  assert.doesNotMatch(page, /\bgetWatchlist\(/);
});
test('cada botón recibe pertenencia normalizada y estado desconocido en fallo', () => {
  assert.match(page, /new Set\(watchlist.items.map\(\(item\) => item.symbol.trim\(\).toUpperCase\(\)\)\)/);
  assert.match(page, /isFollowed=\{followed.has\(r.symbol.trim\(\).toUpperCase\(\)\)\}/);
  assert.match(page, /stateUnknown=\{watchlist.unavailable\}/);
});
