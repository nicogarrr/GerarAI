// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    calculateStrategyScore, getStrategyById, passesStrategyFilters,
    PROPICKS_STRATEGIES, selectRebalancedPicks, type ProPickStrategy,
} from '@/lib/utils/proPicksStrategies';
import type { AdvancedScoreData } from '@/lib/utils/advancedStockScoring';

function score(partial: Partial<AdvancedScoreData['categoryScores']>, overall = 70): AdvancedScoreData {
    return {
        overallScore: overall,
        grade: 'B',
        categoryScores: { value: 0, growth: 0, profitability: 0, cashFlow: 0, momentum: 0, debtLiquidity: 0, ...partial },
        sectorComparison: null,
        reasons: { strengths: [], weaknesses: [], opportunities: [], threats: [] },
        asOf: '2026-10-27T00:00:00Z',
        facts: {},
    };
}

const custom: ProPickStrategy = {
    id: 'test', name: 'Test', description: '',
    categoryWeights: { value: 0.5, growth: 0.5, profitability: 0, cashFlow: 0, momentum: 0, debtLiquidity: 0 },
    filters: { minScore: 60, minCategoryScores: { value: 50 }, sectors: ['Technology'], maxPrice: 100, minMarketCap: 1_000 },
};

describe('PROPICKS_STRATEGIES (constantes)', () => {
    it('los pesos de cada estrategia suman 1', () => {
        for (const s of PROPICKS_STRATEGIES) {
            expect(Object.values(s.categoryWeights).reduce((a, b) => a + b, 0), s.id).toBeCloseTo(1);
        }
    });
});

describe('getStrategyById', () => {
    it('encuentra por id y devuelve undefined si no existe', () => {
        expect(getStrategyById('adaptive')?.name).toBe('Selección Adaptativa IA');
        expect(getStrategyById('inexistente')).toBeUndefined();
    });
});

describe('calculateStrategyScore', () => {
    it('pondera las categorías con los pesos de la estrategia y redondea', () => {
        expect(calculateStrategyScore(score({ value: 100, growth: 50 }), custom)).toBe(75);
        const adaptive = getStrategyById('adaptive')!;
        expect(calculateStrategyScore(score({ value: 100 }), adaptive)).toBe(20);
    });
    it('la estrategia difiere del score general: momentum pesa más en Momentum', () => {
        const momentum = getStrategyById('momentum')!;
        expect(calculateStrategyScore(score({ momentum: 100 }), momentum)).toBe(40);
        expect(calculateStrategyScore(score({ debtLiquidity: 100 }), momentum)).toBe(0);
    });
});

describe('passesStrategyFilters', () => {
    it('rechaza por debajo del score mínimo', () => {
        expect(passesStrategyFilters(score({ value: 100 }, 59), custom, 'Technology', 50, 2000)).toBe(false);
        expect(passesStrategyFilters(score({ value: 100 }, 60), custom, 'Technology', 50, 2000)).toBe(true);
    });
    it('rechaza si una categoría mínima no llega', () => {
        expect(passesStrategyFilters(score({ value: 49 }, 70), custom, 'Technology', 50, 2000)).toBe(false);
    });
    it('rechaza sector no incluido, precio sobre el máximo y market cap bajo', () => {
        expect(passesStrategyFilters(score({ value: 100 }, 70), custom, 'Energy', 50, 2000)).toBe(false);
        expect(passesStrategyFilters(score({ value: 100 }, 70), custom, 'Technology', 150, 2000)).toBe(false);
        expect(passesStrategyFilters(score({ value: 100 }, 70), custom, 'Technology', 50, 500)).toBe(false);
    });
    it('los datos opcionales ausentes no descalifican', () => {
        expect(passesStrategyFilters(score({ value: 100 }, 70), custom)).toBe(true);
    });
});

describe('selectRebalancedPicks', () => {
    const candidates = (n: number, prefix = 'N') =>
        Array.from({ length: n }, (_, i) => ({ symbol: `${prefix}${i}`, score: 100 - i }));

    it('bootstrap sin cartera previa: devuelve el top-20 sin tope de rotación', () => {
        const out = selectRebalancedPicks(candidates(30), [], '2026-10-27');
        expect(out).toHaveLength(20);
        expect(out[0].symbol).toBe('N0');
        expect(out.every((c) => (c as { asOf?: string }).asOf === '2026-10-27')).toBe(true);
    });

    it('mantiene incumbentes dentro del top-30 y rellena con máximo 8 nuevos', () => {
        const prev = ['P0', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'P12', 'P13', 'P14'];
        const all = [
            ...prev.map((symbol, i) => ({ symbol, score: 50 + i })), // ranks 30..44 aprox (por debajo de los nuevos top)
            ...candidates(30),
        ];
        // Los 15 incumbentes (scores 50-64) quedan fuera del top-30 frente a 30 nuevos (70-100):
        // solo entran si están en top-30.
        const out = selectRebalancedPicks(all, prev, '2026-10-27');
        const nuevos = out.filter((c) => !prev.includes(c.symbol));
        expect(nuevos.length).toBeLessThanOrEqual(8);
        expect(out.length).toBeLessThanOrEqual(20);
    });

    it('un incumbente fuera del top-30 se cae aunque estuviera en cartera', () => {
        const prev = ['OLD1'];
        const all = [...candidates(35), { symbol: 'OLD1', score: 1 }]; // rank 35 > 30
        const out = selectRebalancedPicks(all, prev, '2026-10-27');
        expect(out.some((c) => c.symbol === 'OLD1')).toBe(false);
    });

    it('deduplica por símbolo quedándose con el mejor rank', () => {
        const out = selectRebalancedPicks(
            [{ symbol: 'A', score: 50 }, { symbol: 'A', score: 90 }, ...candidates(25)],
            [], '2026-10-27',
        );
        expect(out.filter((c) => c.symbol === 'A')).toHaveLength(1);
    });

    it('usa strategyScore antes que score para ordenar', () => {
        const out = selectRebalancedPicks(
            [
                { symbol: 'ALTO', score: 10, strategyScore: 99 },
                { symbol: 'BAJO', score: 95, strategyScore: 1 },
                // Relleno con score bajo para que no tapen la comparación.
                ...Array.from({ length: 25 }, (_, i) => ({ symbol: `R${i}`, score: 50 - i })),
            ],
            [], '2026-10-27',
        );
        expect(out[0].symbol).toBe('ALTO');
        // BAJO tiene mejor score pero peor strategyScore: queda fuera del top-20.
        expect(out.some((c) => c.symbol === 'BAJO')).toBe(false);
    });

    it('con cartera completa que se mantiene no entra nadie nuevo', () => {
        const prev = Array.from({ length: 20 }, (_, i) => `P${i}`);
        const all = [
            ...prev.map((symbol, i) => ({ symbol, score: 100 - i })), // top-20 exacto
            ...candidates(10), // nuevos con peor score
        ];
        const out = selectRebalancedPicks(all, prev, '2026-10-27');
        expect(out).toHaveLength(20);
        expect(out.every((c) => prev.includes(c.symbol))).toBe(true);
    });
});
