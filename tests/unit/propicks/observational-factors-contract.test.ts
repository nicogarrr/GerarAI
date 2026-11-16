import { describe, expect, it } from 'vitest';

import { CATEGORY_LABEL_EN, CATEGORY_LABEL_ES } from '@/components/proPicks/category-display';
import { PROPICKS_SCORING_WEIGHTS, validateScoreFormula } from '@/lib/utils/propicksValidation';
import { PROPICKS_STRATEGIES } from '@/lib/utils/proPicksStrategies';

/**
 * Contrato factors-v0-observational (front): los factores observacionales
 * (momentum_12_1, factor_quality/momentum/value) NO entran en el score, los
 * pesos ni el ranking; solo cambian etiquetas descriptivas. Estos tests
 * blindan los invariantes: pesos y fórmula intactos, categoría `value`
 * calculada igual y etiqueta nueva sin la palabra «Valor».
 */
describe('contrato factors-v0-observational (front)', () => {
    it('los pesos del score siguen siendo exactamente los documentados', () => {
        expect(PROPICKS_SCORING_WEIGHTS).toEqual({
            value: 0.15,
            growth: 0.2,
            profitability: 0.25,
            cashFlow: 0.15,
            momentum: 0.1,
            debtLiquidity: 0.15,
        });
        const sum = Object.values(PROPICKS_SCORING_WEIGHTS).reduce((a, b) => a + b, 0);
        expect(Math.abs(sum - 1)).toBeLessThan(1e-9);
    });

    it('validateScoreFormula acepta el mismo pick con y sin métricas de factores en facts', () => {
        const categoryScores = { value: 75, growth: 70, profitability: 60, cashFlow: 65, momentum: 55, debtLiquidity: 50 };
        const w = PROPICKS_SCORING_WEIGHTS;
        const score = Math.round(
            categoryScores.value * w.value + categoryScores.growth * w.growth +
            categoryScores.profitability * w.profitability + categoryScores.cashFlow * w.cashFlow +
            categoryScores.momentum * w.momentum + categoryScores.debtLiquidity * w.debtLiquidity,
        );
        const base = {
            symbol: 'TEST',
            score,
            categoryScores,
            reasons: [],
            facts: {} as Record<string, string | number>,
            asOf: '2026-11-16',
            confidenceReasons: [],
        };
        expect(validateScoreFormula(base)).toEqual([]);
        const conFactores = {
            ...base,
            facts: { momentum_12_1: 12.3, factor_quality_pct: 0.8, factor_momentum_pct: 0.6, factor_value_pct: 0.4 },
        };
        expect(validateScoreFormula(conFactores)).toEqual([]);
    });

    it('la categoría value se etiqueta como spread CFROI-WACC, sin «Valor» ni «Valuation»', () => {
        expect(CATEGORY_LABEL_ES.value).toBe('Spread CFROI-WACC');
        expect(CATEGORY_LABEL_EN.value).toBe('CFROI-WACC spread');
        expect(CATEGORY_LABEL_ES.value).not.toMatch(/valor/i);
        expect(CATEGORY_LABEL_EN.value).not.toMatch(/valuation/i);
    });

    it('la estrategia value se renombra sin tocar pesos ni minScore', () => {
        const value = PROPICKS_STRATEGIES.find((s) => s.id === 'value');
        expect(value).toBeDefined();
        expect(value!.name).toBe('Calidad-valor (spread CFROI-WACC)');
        expect(value!.categoryWeights).toEqual({
            value: 0.35,
            growth: 0.05,
            profitability: 0.25,
            cashFlow: 0.15,
            momentum: 0.05,
            debtLiquidity: 0.15,
        });
        expect(value!.filters?.minScore).toBe(60);
    });
});
