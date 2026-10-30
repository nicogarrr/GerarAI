import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = readFileSync('components/portfolio/PortfolioHoldings.tsx', 'utf8');
test('mobile and desktop do not format a made-up zero return without cost or conversion', () => {
 assert.equal((source.match(/const gainKnown = !holding\.fxMissing && holding\.cost > 0;/g) ?? []).length, 2);
 assert.equal((source.match(/gainKnown \? f\.formatPercent\(holding\.gainPercent/g) ?? []).length, 2);
 assert.equal((source.match(/!gainKnown \? 'text-gray-400'/g) ?? []).length, 4);
 assert.equal((source.match(/holding\.avgPrice > 0 \? format\(holding\.avgPrice, holding\.nativeCurrency\) : ti\('common\.na'\)/g) ?? []).length, 2);
 assert.ok(!source.includes('FX missing'));
});
