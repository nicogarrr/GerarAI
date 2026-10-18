import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: node requires the explicit extension.
import { formatMarketDate, formatUserDateTime } from '../lib/format.ts';

test('market dates stay on the quoted day and show a Spanish month', () => {
  assert.equal(formatMarketDate('2026-10-16'), '16 oct 2026');
  assert.equal(formatMarketDate(null), 'N/D');
  assert.match(formatUserDateTime('2026-10-18T14:30:00Z', { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }), /16:30.*CEST/);
});
test('watchlist and movers do not interpolate raw quote dates', () => {
  const watchlist = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
  const movers = readFileSync('app/(root)/movers/page.tsx', 'utf8');
  assert.equal(watchlist.match(/formatMarketDate\(stock.priceAsOf\)/g)?.length, 2);
  assert.ok(watchlist.includes('col-span-2 min-w-0'));
  assert.ok(movers.includes('formatMarketDate(row.date)'));
  assert.ok(movers.includes("timeZoneName: 'short'"));
  assert.ok(!movers.includes('{row.date}'));
});

test('screener: el precio de vela diaria se rotula como cierre con su fecha, no como hora de cotización', () => {
  const page = readFileSync('app/(root)/screener/page.tsx', 'utf8');
  assert.match(page, /r\.priceDate \? `Cierre \$\{formatMarketDate\(r\.priceDate\)\}` : quoteObserved\(r\.priceAsOf\)/);
});
