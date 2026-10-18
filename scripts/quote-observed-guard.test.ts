import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error node strip-types requires extension.
import { quoteObserved } from '../lib/market/quote-observed.ts';
test('quote label uses vendor timestamp with explicit UTC, not a claimed close', () => {
 assert.match(quoteObserved(1792180800), /^Cotización .*2026.*UTC$/);
 assert.doesNotMatch(quoteObserved(1792180800), /Cierre/);
 for(const missing of [null, undefined, 0, NaN]) assert.equal(quoteObserved(missing),'Fecha N/D: proveedor sin fecha');
});

test('daily candle opening timestamp never claims a closing time',()=>{
 assert.match(quoteObserved(1792180800,'daily_candle_open'),/^Última vela diaria \(hora de apertura\).*UTC$/);
 assert.doesNotMatch(quoteObserved(1792180800,'daily_candle_open'),/Cierre|Cotización/);
});
