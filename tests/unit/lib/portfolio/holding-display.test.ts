// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { holdingDisplayMode, valuationHoldLabel } from '@/lib/portfolio/holding-display';

describe('holdingDisplayMode', () => {
    it('con coste y divisa disponible muestra la rentabilidad', () => {
        expect(holdingDisplayMode({ cost: 1000, value: 1100, valueMissing: false, fxMissing: false })).toBe('gain');
    });
    it('sin base de coste pero con valor convertible muestra solo el valor (rentabilidad N/D)', () => {
        expect(holdingDisplayMode({ cost: 0, value: 1100, valueMissing: false, fxMissing: false })).toBe('value');
    });
    it('con coste pero sin tipo de cambio no puede mostrar rentabilidad: cae a valor', () => {
        expect(holdingDisplayMode({ cost: 1000, value: 1100, valueMissing: false, fxMissing: true })).toBe('value');
    });
    it('sin coste y sin valor: N/D', () => {
        expect(holdingDisplayMode({ cost: 0, value: 0, valueMissing: true, fxMissing: false })).toBe('na');
        expect(holdingDisplayMode({ cost: 0, value: 0, valueMissing: false, fxMissing: true })).toBe('na');
    });
    it('un valor ausente (valueMissing) no cuenta como valor aunque llegue un número', () => {
        expect(holdingDisplayMode({ cost: 0, value: 500, valueMissing: true, fxMissing: false })).toBe('na');
    });
});

describe('valuationHoldLabel', () => {
    it('explica el motivo con la fecha en formato dd/mm/aaaa', () => {
        expect(valuationHoldLabel({ reason: 'split', effectiveDate: '2026-06-02' }))
            .toBe('Valoración pendiente: split del 02/06/2026 sin precio post-split verificado');
    });
    it('sin fecha no inventa ninguna', () => {
        expect(valuationHoldLabel({ reason: 'split', effectiveDate: null }))
            .toBe('Valoración pendiente: sin precio post-split verificado');
    });
});
