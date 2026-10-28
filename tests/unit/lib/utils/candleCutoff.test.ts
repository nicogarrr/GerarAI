// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { filterCandlesUpTo } from '@/lib/utils/candleCutoff';

const D = 86_400;
const base = Date.UTC(2026, 0, 1) / 1000; // segundos Unix (contrato Finnhub)

describe('filterCandlesUpTo', () => {
    it('excluye SIEMPRE las velas posteriores al corte: el corte filtra, no etiqueta', () => {
        const series = { prices: [10, 11, 12, 13], dates: [base, base + D, base + 2 * D, base + 3 * D] };
        const out = filterCandlesUpTo(series, new Date((base + D) * 1000).toISOString());
        expect(out).toEqual({ prices: [10, 11], dates: [base, base + D] });
    });
    it('una vela en el instante exacto del corte entra (t <= corte)', () => {
        const series = { prices: [10, 11], dates: [base, base + D] };
        const out = filterCandlesUpTo(series, new Date((base + D) * 1000).toISOString());
        expect(out.prices).toEqual([10, 11]);
    });
    it('con corte inválido devuelve la serie intacta (lo decide el llamador)', () => {
        const series = { prices: [10], dates: [base] };
        expect(filterCandlesUpTo(series, 'no-es-fecha')).toBe(series);
    });
    it('si prices y dates no miden igual usa el tramo común', () => {
        const series = { prices: [10, 11, 12], dates: [base, base + D] };
        const out = filterCandlesUpTo(series, new Date((base + 10 * D) * 1000).toISOString());
        expect(out).toEqual({ prices: [10, 11], dates: [base, base + D] });
    });
    it('corte anterior a todas las velas devuelve serie vacía', () => {
        const series = { prices: [10], dates: [base] };
        expect(filterCandlesUpTo(series, '2020-01-01T00:00:00.000Z')).toEqual({ prices: [], dates: [] });
    });
});
