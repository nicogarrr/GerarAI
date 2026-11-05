import { describe, expect, it } from 'vitest';
// @ts-expect-error Node regression harness requires an explicit extension.
import { preferCandlesticks } from '@/lib/market/technical.ts';

const ohlc = (day: string, base: number) => ({ date: day, open: base, high: base + 2, low: base - 2, close: base + 1, volume: 1000 });

describe('preferCandlesticks (la línea diaria muestra velas cuando existen OHLC)', () => {
    it('todas las barras diarias con OHLC -> velas', () => {
        expect(preferCandlesticks([ohlc('2026-11-02', 100), ohlc('2026-11-03', 101)], false)).toBe(true);
    });
    it('una sola barra sin OHLC -> línea de cierres para todo el tramo', () => {
        const sinOhlc = { date: '2026-11-04', open: null, high: null, low: null, close: 103, volume: null };
        expect(preferCandlesticks([ohlc('2026-11-02', 100), sinOhlc], false)).toBe(false);
    });
    it('OHLC incoherente (high < low) no es vela', () => {
        const roto = { date: '2026-11-04', open: 100, high: 99, low: 101, close: 100, volume: 1 };
        expect(preferCandlesticks([ohlc('2026-11-02', 100), roto], false)).toBe(false);
    });
    it('intradía siempre línea aunque haya OHLC', () => {
        expect(preferCandlesticks([ohlc('2026-11-02', 100), ohlc('2026-11-03', 101)], true)).toBe(false);
    });
    it('menos de 2 barras no dibuja velas', () => {
        expect(preferCandlesticks([ohlc('2026-11-02', 100)], false)).toBe(false);
        expect(preferCandlesticks([], false)).toBe(false);
    });
});
