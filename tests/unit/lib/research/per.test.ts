import { describe, expect, it } from 'vitest';
import { perState } from '@/lib/research/per';

const base = { quoteSymbol: 'AAPL', ticker: 'AAPL', peTTM: 28.4, providerAvailable: true };

describe('perState', () => {
    it('PER válido de listado US', () => {
        expect(perState(base)).toEqual({ value: 28.4, note: 'Finnhub · últimos 12 meses' });
    });
    it('sin listado verificado: N/D con motivo', () => {
        expect(perState({ ...base, quoteSymbol: null })).toEqual({ value: null, note: 'Sin listado de cotización verificado' });
    });
    it('listado distinto al ticker (ADR u homónimo) no usa el PER ajeno', () => {
        const r = perState({ ...base, quoteSymbol: 'BABA', ticker: '9988.HK' });
        expect(r.value).toBeNull();
        expect(r.note).toMatch(/fuera de EE\. UU\./);
    });
    it('usLine=false manda aunque símbolo y ticker coincidan', () => {
        expect(perState({ ...base, usLine: false }).value).toBeNull();
    });
    it('usLine=true manda sobre la igualdad símbolo==ticker', () => {
        expect(perState({ ...base, quoteSymbol: 'BRK.B', ticker: 'brk-b', usLine: true }).value).toBeNull();
    });
    it('ticker con espacios y minúsculas se normaliza', () => {
        expect(perState({ ...base, ticker: ' aapl ' }).value).toBe(28.4);
    });
    it('proveedor caído: no inventa', () => {
        expect(perState({ ...base, providerAvailable: false })).toEqual({ value: null, note: 'Proveedor de métricas no disponible' });
    });
    it.each([[-5], [0], [NaN], [Infinity], ['12'], [null], [undefined]])('PER %s no es verificable', (pe) => {
        const r = perState({ ...base, peTTM: pe });
        expect(r.value).toBeNull();
        expect(r.note).toMatch(/no informa PER/);
    });
});
