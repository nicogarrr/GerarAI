import { describe, expect, it } from 'vitest';

import { form13fValueToUsd } from '@/lib/form13f-value';
import { marketIndexUnit } from '@/lib/marketIndexUnit';
import { createLatestRequestGate } from '@/lib/latest-request';
import { buildAllocationSlices, CASH_SLICE_SYMBOL } from '@/lib/portfolio-allocation';

describe('form13fValueToUsd', () => {
    it('raw nulo o sin fecha devuelve null', () => {
        expect(form13fValueToUsd(null, '2023-03-31')).toBeNull();
        expect(form13fValueToUsd(undefined, '2023-03-31')).toBeNull();
        expect(form13fValueToUsd(123, null)).toBeNull();
        expect(form13fValueToUsd(123, undefined)).toBeNull();
        expect(form13fValueToUsd(123, '')).toBeNull();
    });

    it('informes desde el 31-12-2022 ya van en dólares: se devuelven tal cual', () => {
        expect(form13fValueToUsd(250_000_000, '2022-12-31')).toBe(250_000_000);
        expect(form13fValueToUsd(250_000_000, '2023-03-31')).toBe(250_000_000);
    });

    it('informes anteriores al 31-12-2022 van en miles: se multiplica por 1000', () => {
        expect(form13fValueToUsd(250_000, '2022-12-30')).toBe(250_000_000);
        expect(form13fValueToUsd(1, '1999-06-30')).toBe(1000);
    });
});

describe('marketIndexUnit', () => {
    it('la unidad declarada por el backend manda', () => {
        expect(marketIndexUnit('AAPL', 'usd')).toBe('usd');
        expect(marketIndexUnit('BTC-USD', 'index')).toBe('index');
    });

    it('sin unit, el prefijo ^ de Yahoo es nivel de índice', () => {
        expect(marketIndexUnit('^GSPC')).toBe('index');
        expect(marketIndexUnit('^IXIC')).toBe('index');
        expect(marketIndexUnit('^IBEX', null)).toBe('index');
    });

    it('símbolos conocidos sin unit usan la tabla', () => {
        expect(marketIndexUnit('BTC-USD')).toBe('usd');
        expect(marketIndexUnit('GC=F')).toBe('usd');
        expect(marketIndexUnit('SI=F')).toBe('usd');
    });

    it('símbolo desconocido sin unit devuelve null: no se inventa la unidad', () => {
        expect(marketIndexUnit('AAPL')).toBeNull();
        expect(marketIndexUnit('NESN.SW', 'otra')).toBeNull();
    });
});

describe('createLatestRequestGate', () => {
    it('solo el último ticket es válido', () => {
        const gate = createLatestRequestGate();
        const first = gate.begin();
        const second = gate.begin();
        expect(gate.isLatest(first)).toBe(false);
        expect(gate.isLatest(second)).toBe(true);
    });

    it('invalidate descarta la petición en vuelo', () => {
        const gate = createLatestRequestGate();
        const ticket = gate.begin();
        gate.invalidate();
        expect(gate.isLatest(ticket)).toBe(false);
        const next = gate.begin();
        expect(gate.isLatest(next)).toBe(true);
    });
});

describe('buildAllocationSlices', () => {
    it('reparte el 100 % solo entre posiciones y ordena por valor descendente', () => {
        const slices = buildAllocationSlices([
            { symbol: 'KO', value: 25, gain: 1, gainPercent: 4 },
            { symbol: 'AAPL', value: 75, gain: 5, gainPercent: 7 },
        ]);
        expect(slices.map((s) => s.symbol)).toEqual(['AAPL', 'KO']);
        expect(slices[0].percentage).toBeCloseTo(75, 6);
        expect(slices[1].percentage).toBeCloseTo(25, 6);
        expect(slices.reduce((sum, s) => sum + s.percentage, 0)).toBeCloseTo(100, 6);
        expect(slices[0].gain).toBe(5);
        expect(slices[0].gainPercent).toBe(7);
    });

    it('sin posiciones devuelve lista vacía', () => {
        expect(buildAllocationSlices([])).toEqual([]);
    });

    it('con valor total no positivo los porcentajes son 0, nunca negativos ni >100', () => {
        const slices = buildAllocationSlices([
            { symbol: 'AAPL', value: 0, gain: 0, gainPercent: 0 },
        ]);
        expect(slices[0].percentage).toBe(0);
    });

    it('el símbolo de caja reservado sigue disponible para el tooltip', () => {
        expect(CASH_SLICE_SYMBOL).toBe('Caja');
    });
});
