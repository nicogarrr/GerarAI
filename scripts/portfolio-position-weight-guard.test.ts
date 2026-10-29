import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error node strip-types needs explicit extension.
import { buildAllocationSlices } from '../lib/portfolio-allocation.ts';
test('position weights use the same valued subset and helper as Resumen', () => {
 const src=readFileSync('components/portfolio/PortfolioHoldings.tsx','utf8');
 assert.match(src,/buildAllocationSlices\(currentHoldings.filter/);
 assert.match(src,/!holding.valueMissing && !holding.valuationHold/);
 assert.match(src,/>Peso<\/dt>/);
 assert.match(src,/>Peso<\/TableHead>/);
 assert.equal((src.match(/weight\(holding.symbol\)/g) ?? []).length,2);
 const slices=buildAllocationSlices([{symbol:'GOOGL',value:249,gain:0,gainPercent:0},{symbol:'AAPL',value:201,gain:0,gainPercent:0},{symbol:'V',value:550,gain:0,gainPercent:0}]);
 assert.equal(slices.find((slice)=>slice.symbol==='GOOGL')?.percentage,24.9);
});
