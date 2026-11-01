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
  const movers = (readFileSync('components/market/MoversTable.tsx', 'utf8') + readFileSync('app/(root)/screener/page.tsx', 'utf8'));
  assert.equal(watchlist.match(/formatMarketDate\(stock.priceAsOf\)/g)?.length, 2);
  assert.ok(watchlist.includes('col-span-2 min-w-0'));
  assert.ok(movers.includes('formatMarketDate(row.date)'));
  assert.ok(movers.includes("timeZoneName: 'short'"));
  assert.ok(!movers.includes('{row.date}'));
});

test('screener: una fecha de barra diaria no certifica cierre ni tiempo real', () => {
  const page = readFileSync('app/(root)/screener/page.tsx', 'utf8');
  // Las barras diarias también pueden proceder de backfills durante sesión.
  // La fecha no prueba cierre: no inferirlo del origen ni de la hora local.
  assert.match(page, /r\.priceDate \? t\('screener\.dailyData', \{ date: formatMarketDate\(r\.priceDate[,)].*\}\) : quoteObserved\(r\.priceAsOf, r\.priceTimestampKind[,)]/);
  assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/screener.json', 'utf8')).dailyData, 'Dato diario del {date}');
  assert.doesNotMatch(page, /`Cierre \$\{formatMarketDate\(r\.priceDate\)\}`/);
});
