// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    validateNoFutureData, validateNumbersTraceable, validateOverlays, validatePicks,
    validateReasonsTraceable, validateScoreFormula, valueTextVariants, type PickLike,
} from '@/lib/utils/propicksValidation';

const NOW = new Date('2026-10-27T12:00:00Z');

function validPick(): PickLike {
    return {
        symbol: 'SAN',
        asOf: '2026-10-27T10:00:00Z',
        facts: { pe: 8.5, price: 4, targetMean: 6, ov_vix: 40.5 },
        confidenceReasons: [
            { text: 'PER bajo (8,5)', metric: 'pe', value: 8.5 },
            { text: 'Precio actual 4', metric: 'price', value: 4 },
        ],
        currentPrice: 4,
        targetPrice: 6,
        upsidePotential: 50,
        score: 82, // 15+16+22.5+10.5+6+12 = 82 (fórmula con pesos canónicos)
        categoryScores: { value: 100, growth: 80, profitability: 90, cashFlow: 70, momentum: 60, debtLiquidity: 80 },
        overlays: [{ metric: 'ov_vix', value: 40.5, detail: 'VIX en 40,5 (valor 40.5)' }],
    };
}

describe('valueTextVariants', () => {
    it('admite la forma cruda y la es-ES con coma decimal', () => {
        expect(valueTextVariants(50.2)).toEqual(['50.2', '50,2']);
    });
    it('un entero sin diferencia de formato da una sola variante', () => {
        expect(valueTextVariants(50)).toEqual(['50']);
    });
    it('un string se devuelve tal cual', () => {
        expect(valueTextVariants('tesis')).toEqual(['tesis']);
    });
});

describe('R1: sin datos futuros', () => {
    it('un pick bien cortado no da issues', () => {
        expect(validateNoFutureData(validPick(), NOW)).toEqual([]);
    });
    it('falta asOf o es inválido', () => {
        expect(validateNoFutureData({ ...validPick(), asOf: '' }, NOW)[0].message).toContain('falta asOf');
        expect(validateNoFutureData({ ...validPick(), asOf: 'ayer' }, NOW)[0].message).toContain('asOf inválido');
    });
    it('asOf posterior a ahora (más allá del skew de 5 min) señala datos futuros', () => {
        const r = validateNoFutureData({ ...validPick(), asOf: '2026-10-27T13:00:00Z' }, NOW);
        expect(r[0].message).toContain('posterior a ahora');
        // dentro del skew de reloj pasa
        expect(validateNoFutureData({ ...validPick(), asOf: '2026-10-27T12:04:00Z' }, NOW)).toEqual([]);
    });
});

describe('R2: motivos trazables', () => {
    it('exige al menos 2 motivos', () => {
        const r = validateReasonsTraceable({ ...validPick(), confidenceReasons: [{ text: 'PER 8,5', metric: 'pe', value: 8.5 }] });
        expect(r[0].message).toContain('al menos 2 motivos');
    });
    it('un motivo que referencia una métrica ausente en facts no es verificable', () => {
        const pick = validPick();
        pick.confidenceReasons[0] = { text: 'PER 8,5', metric: 'pb', value: 8.5 };
        expect(validateReasonsTraceable(pick).some((i) => i.message.includes('ausente en facts'))).toBe(true);
    });
    it('el valor del motivo debe coincidir con facts (tolerancia 0.51)', () => {
        const pick = validPick();
        pick.confidenceReasons[0] = { text: 'PER 9,5', metric: 'pe', value: 9.5 };
        expect(validateReasonsTraceable(pick).some((i) => i.message.includes('≠ facts.pe'))).toBe(true);
        pick.confidenceReasons[0] = { text: 'PER 8,9', metric: 'pe', value: 8.9 };
        expect(validateReasonsTraceable(pick)).toEqual([]);
    });
    it('el texto del motivo debe mostrar el valor (crudo o es-ES)', () => {
        const pick = validPick();
        pick.confidenceReasons[0] = { text: 'PER bajo', metric: 'pe', value: 8.5 };
        expect(validateReasonsTraceable(pick).some((i) => i.message.includes('no muestra su valor'))).toBe(true);
        // Formato español con coma también verifica
        pick.confidenceReasons[0] = { text: 'PER 8,5', metric: 'pe', value: 8.5 };
        expect(validateReasonsTraceable(pick)).toEqual([]);
    });
});

describe('R3: números coherentes', () => {
    it('currentPrice/targetPrice deben coincidir con facts (±0.5 o 2 %)', () => {
        expect(validateNumbersTraceable({ ...validPick(), currentPrice: 8 })[0].message).toContain('currentPrice');
        expect(validateNumbersTraceable({ ...validPick(), targetPrice: 12 })[0].message).toContain('targetPrice');
        expect(validateNumbersTraceable(validPick())).toEqual([]);
    });
    it('upsidePotential debe reproducir (target-price)/price', () => {
        expect(validateNumbersTraceable({ ...validPick(), upsidePotential: 10 })[0].message).toContain('upsidePotential (10) ≠ calculado (50.00)');
        expect(validateNumbersTraceable({ ...validPick(), upsidePotential: 50.4 })).toEqual([]);
    });
    it('sin precios positivos no se puede comprobar: no acusa', () => {
        const pick = validPick();
        delete pick.currentPrice;
        delete pick.targetPrice;
        expect(validateNumbersTraceable(pick)).toEqual([]);
    });
});

describe('R4: fórmula del score', () => {
    it('el score reproduce la fórmula con pesos canónicos', () => {
        expect(validateScoreFormula(validPick())).toEqual([]);
    });
    it('divergencia mayor que ±1 (redondeo) es issue', () => {
        expect(validateScoreFormula({ ...validPick(), score: 50 })[0].rule).toBe('R4-score');
    });
    it('una categoría sin número es issue directa', () => {
        const pick = validPick();
        pick.categoryScores = { ...pick.categoryScores, momentum: 'alto' as never };
        expect(validateScoreFormula(pick)[0].message).toContain('"momentum"');
    });
});

describe('R5: overlays trazables', () => {
    it('overlay válido: facts.ov_<metric> con el mismo valor y detail que lo muestra', () => {
        expect(validateOverlays(validPick())).toEqual([]);
    });
    it('la métrica sin prefijo ov_ se normaliza igual que en las actions', () => {
        const pick = validPick();
        pick.overlays = [{ metric: 'vix', value: 40.5, detail: 'VIX (valor 40.5)' }];
        expect(validateOverlays(pick)).toEqual([]);
    });
    it('falta el volcado en facts: número no verificable', () => {
        const pick = validPick();
        delete pick.facts.ov_vix;
        expect(validateOverlays(pick).some((i) => i.message.includes('falta facts.ov_vix'))).toBe(true);
    });
    it('detail sin el valor literal no es verificable en UI', () => {
        const pick = validPick();
        pick.overlays = [{ metric: 'ov_vix', value: 40.5, detail: 'VIX alto' }];
        expect(validateOverlays(pick).some((i) => i.message.includes('detail no muestra su valor'))).toBe(true);
    });
    it('overlay sin metric no se puede trazar', () => {
        const pick = validPick();
        pick.overlays = [{ metric: '', value: 1, detail: '1' }];
        expect(validateOverlays(pick)[0].message).toContain('overlay sin metric');
    });
});

describe('validatePicks', () => {
    it('junta las 5 reglas sobre la lista; vacío = todo válido', () => {
        expect(validatePicks([validPick()], NOW)).toEqual([]);
        expect(validatePicks([validPick(), { ...validPick(), symbol: 'X', asOf: '' }], NOW)).toHaveLength(1);
    });
});
