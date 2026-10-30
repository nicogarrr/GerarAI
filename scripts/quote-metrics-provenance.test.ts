import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: extensión necesaria en node --experimental-strip-types.
import { datedQuoteMetrics } from '../lib/market/quote-metrics.ts';
const quote = { source: 'Finnhub' as const, t: 1791298800, o: 20, h: 22, l: 19, pc: 18 };
describe('procedencia OHLC', () => {
    it('quote descartada y cierre de vela no se mezclan', () => {
        const m = datedQuoteMetrics(quote, false);
        assert.equal(m.open, null); assert.equal(m.high, null); assert.equal(m.low, null);
        assert.equal(m.source, null); assert.equal(m.timestamp, null);
    });
    it('fallback Yahoo o proveedor sin timestamp no publica métricas', () => {
        for (const q of [{ ...quote, t: null }, { ...quote, source: undefined }, { ...quote, source: 'Yahoo Finance' as const }, null]) {
            assert.equal(datedQuoteMetrics(q, true).open, null);
        }
    });
    it('quote saneada conocida conserva timestamp y fuente, pc sin fecha propia no se publica', () => {
        const m = datedQuoteMetrics(quote, true);
        assert.equal(m.open, 20); assert.equal(m.high, 22); assert.equal(m.low, 19);
        assert.equal(m.source, 'Finnhub'); assert.equal(m.timestamp, quote.t);
        assert.equal(m.previousClose, null);
    });
    it('acción usa el filtro y UI exige metadata fechada', () => {
        const action = readFileSync('lib/actions/market-workspace.actions.ts', 'utf8');
        assert.match(action, /datedQuoteMetrics\(quote, quoteUsable\)/);
        assert.match(action, /metricsSession: metrics.timestamp \? sessionDateEt\(metrics.timestamp\)/);
        assert.doesNotMatch(action, /open: quote\?\.o/);
        const ui = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
        assert.match(ui, /hasDatedMetrics \? quote!.open : null/);
        // La línea de procedencia bajo el precio se quitó a petición de Nico (30-oct-2026);
        // la fecha del cierre anterior sigue visible en la tira de métricas.
        assert.match(ui, /quoteDate\(quote\.previous_close_timestamp\)/);
        assert.doesNotMatch(ui, /\['Cierre anterior', quote\?\.previous_close\]/);
        assert.match(ui, /\['Cierre anterior', quote\?\.previous_close_timestamp \|\| quote\?\.previous_close_date \? quote.previous_close : null\]/);
    });
});
