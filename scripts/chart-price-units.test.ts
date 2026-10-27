import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error explicit extension required for node strip types
import { normalizeChartPriceUnits } from '../lib/market/chart-price-units.ts';
const bars = [{ open: 4200, high: 4400, low: 4100, close: 4300, volume: 12, date: '2026-10-27' }];
for (const [unit, major] of [['GBp','GBP'], ['GBX','GBP'], ['ZAc','ZAR'], ['ILA','ILS']]) {
    test(`normalizes all OHLC from ${unit} to ${major}, preserving dates and volume`, () => {
        const result = normalizeChartPriceUnits(bars, {ticker: 'DEMO', currency: major, candleCurrency: unit});
        assert.equal(result.currency, major);
        assert.deepEqual(result.bars[0], {...bars[0], open:42, high:44, low:41, close:43});
    });
}
test('GBP master does not relabel GBp raw numbers and missing .L metadata stays closed', () => {
    assert.equal(normalizeChartPriceUnits(bars, {ticker:'DEMO.L',currency:'GBP',candleCurrency:'GBp'}).bars[0].close,43);
    assert.deepEqual(normalizeChartPriceUnits(bars, {ticker:'DEMO.L',currency:'GBP'}).bars,[]);
    assert.deepEqual(normalizeChartPriceUnits(bars, {ticker:'DEMO.L',currency:'GBX'}).bars,[]);
    assert.deepEqual(normalizeChartPriceUnits(bars, {ticker:'DEMO.L',currency:'GBP',candleCurrency:'USD'}).bars,[]);
});
test('ordinary major-unit legacy and explicit-major London candles remain supported', () => {
    assert.equal(normalizeChartPriceUnits(bars, {ticker:'AAPL',currency:'USD'}).bars[0].close,4300);
    assert.equal(normalizeChartPriceUnits(bars, {ticker:'DEMO.L',currency:'GBP',candleCurrency:'GBP'}).bars[0].close,4300);
});
