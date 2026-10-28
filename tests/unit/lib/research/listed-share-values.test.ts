import { describe, expect, it } from 'vitest';
import { thesisScenarioDisplay, valuationScenarioDisplay } from '@/lib/research/listed-share-values';

const original = { bear: 10, base: 20, bull: 30, expected: 21 };

describe('thesisScenarioDisplay', () => {
    it('sin base: valores originales y aviso de base no verificada', () => {
        expect(thesisScenarioDisplay(original, null)).toEqual({ values: original, label: ' (base por acción no verificada)' });
        expect(thesisScenarioDisplay(original, undefined).label).toMatch(/no verificada/);
    });
    it('con valores por título cotizado: usa esos, no los originales (ADR)', () => {
        const r = thesisScenarioDisplay(original, { adr_ratio: 2, listed_share_values: { bear: 5, base: 10, bull: 15, expected: 10.5 } });
        expect(r.values).toEqual({ bear: 5, base: 10, bull: 15, expected: 10.5 });
        expect(r.label).toBe(' (por ADR, ×2)');
    });
    it('un escenario no finito/ausente pasa a null, no a 0', () => {
        const r = thesisScenarioDisplay(original, { listed_share_values: { bear: NaN, base: 10 } });
        expect(r.values).toEqual({ bear: null, base: 10, bull: null, expected: null });
        expect(r.label).toBe(' (por ADR)');
    });
    it('ratio ADR inválido (0, negativo, NaN) no se muestra', () => {
        for (const ratio of [0, -2, NaN, null]) {
            expect(thesisScenarioDisplay(original, { adr_ratio: ratio as number, listed_share_values: { base: 1 } }).label).toBe(' (por ADR)');
        }
    });
    it('sin valores listados y ratio != 1: base no verificada; con ratio 1 o sin ratio: sin aviso', () => {
        expect(thesisScenarioDisplay(original, { adr_ratio: 3 })).toEqual({ values: original, label: ' (base por acción no verificada)' });
        expect(thesisScenarioDisplay(original, { adr_ratio: 1 }).label).toBe('');
        expect(thesisScenarioDisplay(original, {}).label).toBe('');
    });
});

describe('valuationScenarioDisplay', () => {
    it('sin base no avisa (a diferencia de la tesis)', () => {
        expect(valuationScenarioDisplay(original, null)).toEqual({ values: original, label: '' });
    });
    it('con valores por título usa esos', () => {
        const r = valuationScenarioDisplay(original, { adr_ratio: 0.5, listed_share_values: { base: 40 } });
        expect(r.values.base).toBe(40);
        expect(r.label).toBe(' (por ADR, ×0.5)');
    });
    it('listed_share_values no objeto se ignora', () => {
        expect(valuationScenarioDisplay(original, { listed_share_values: 'x' as never, adr_ratio: 4 }).label).toMatch(/no verificada/);
    });
});
