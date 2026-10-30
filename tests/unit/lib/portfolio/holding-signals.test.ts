// @vitest-environment node
// NOTA: las funciones de nivel DCA (mapDcaSignals, dcaLevelText) pertenecen a la
// zona congelada DCA y no se ejercitan aquí a propósito.
import { describe, expect, it } from 'vitest';
import { fairValueGapPercent, mapFairValues, type HoldingFairValue } from '@/lib/portfolio/holding-signals';

describe('mapFairValues', () => {
    it('mapea lecturas válidas a mayúsculas con su procedencia', () => {
        const out = mapFairValues({
            items: {
                san: { value: 5.2, source: 'tesis', label: 'Tesis', as_of: '2026-10-01', currency: 'EUR', publishable: true },
            },
        });
        expect(out.SAN).toEqual({ value: 5.2, source: 'tesis', label: 'Tesis', asOf: '2026-10-01', currency: 'EUR', publishable: true });
    });

    it('descarta valores no positivos, no finitos o fuentes desconocidas: nunca se inventa un valor justo', () => {
        const out = mapFairValues({
            items: {
                A: { value: 0, source: 'tesis' },
                B: { value: -3, source: 'motor' },
                C: { value: NaN, source: 'motor' },
                D: { value: Infinity, source: 'motor' },
                E: { value: 10, source: 'chatgpt' },
                F: { value: 'diez', source: 'tesis' },
                G: 'no es un objeto',
            },
        });
        expect(out).toEqual({});
    });

    it('etiqueta por defecto «Valor justo» y publishable solo si es true explícito', () => {
        const out = mapFairValues({ items: { REP: { value: 12, source: 'motor_orientativo' } } });
        expect(out.REP).toMatchObject({ label: 'Valor justo', asOf: null, currency: null, publishable: false });
    });

    it('una respuesta sin items devuelve mapa vacío', () => {
        expect(mapFairValues(null)).toEqual({});
        expect(mapFairValues({ items: 'no' })).toEqual({});
    });
});

describe('fairValueGapPercent', () => {
    const fair: HoldingFairValue = { value: 6, source: 'tesis', label: 'Tesis', asOf: null, currency: 'EUR', publishable: true };

    it('positivo cuando el valor justo supera al precio (margen al alza)', () => {
        expect(fairValueGapPercent(5, 'EUR', fair)).toBe(20);
    });
    it('negativo cuando el precio supera al valor justo', () => {
        expect(fairValueGapPercent(7.5, 'EUR', fair)).toBe(-20);
    });
    it('la comparación de divisa no distingue mayúsculas', () => {
        expect(fairValueGapPercent(5, 'eur', fair)).toBe(20);
    });
    it('Londres en peniques se compara en libras, nunca GBp como GBP', () => {
        // Valor justo 15 £; cotización 1.200 GBp = 12 £ -> (15 - 12) / 12 = 25 %.
        const gbp: HoldingFairValue = { ...fair, value: 15, currency: 'GBP' };
        expect(fairValueGapPercent(1200, 'GBp', gbp)).toBeCloseTo(25);
        expect(fairValueGapPercent(1200, 'GBX', gbp)).toBeCloseTo(25);
        expect(fairValueGapPercent(12, 'GBP', gbp)).toBeCloseTo(25);
        expect(fairValueGapPercent(12, 'GBP', { ...gbp, currency: 'GBp' })).toBeNull();
    });
    it.each([
        ['divisas distintas (nunca se mezclan)', 5, 'USD'],
        ['divisa del precio ausente', 5, null],
        ['precio 0', 0, 'EUR'],
        ['precio negativo', -5, 'EUR'],
        ['precio NaN', NaN, 'EUR'],
    ])('devuelve null con %s', (_e, price, currency) => {
        expect(fairValueGapPercent(price, currency, fair)).toBeNull();
    });
    it('sin valor justo o sin divisa del valor justo: null', () => {
        expect(fairValueGapPercent(5, 'EUR', null)).toBeNull();
        expect(fairValueGapPercent(5, 'EUR', { ...fair, currency: null })).toBeNull();
    });
});
