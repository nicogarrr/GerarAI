import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = readFileSync('components/portfolio/PortfolioHoldings.tsx', 'utf8');
test('mobile and desktop do not format a made-up zero return without cost, quote or conversion', () => {
 // Una sola regla compartida (#3252 añadió quoteMissing, #3262 la extrajo a un helper):
 // sin FX, sin cotización real o sin coste no hay rentabilidad que mostrar.
 const helper = source.match(/export function holdingGainKnown\(h: PortfolioHolding\): boolean \{\s*return ([^;]+);/);
 assert.ok(helper, 'holdingGainKnown debe existir');
 for (const cond of ['!h.fxMissing', '!h.quoteMissing', 'h.cost > 0']) assert.ok(helper[1].includes(cond), `holdingGainKnown debe exigir ${cond}`);
 assert.equal((source.match(/const gainKnown = holdingGainKnown\(holding\);/g) ?? []).length, 2);
 assert.equal((source.match(/gainKnown \? f\.formatPercent\(holding\.gainPercent/g) ?? []).length, 2);
 assert.equal((source.match(/!gainKnown \? 'text-gray-400'/g) ?? []).length, 4);
 assert.equal((source.match(/holding\.avgPrice > 0 \? format\(holding\.avgPrice, holding\.nativeCurrency\) : ti\('common\.na'\)/g) ?? []).length, 2);
 assert.ok(!source.includes('FX missing'));
});
