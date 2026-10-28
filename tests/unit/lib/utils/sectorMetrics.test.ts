// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    calculateAverage, computeComparableCategoryScores, normalizeDebtScore,
    normalizeGrowthScore, normalizeProfitabilityScore, normalizeValueScore,
} from '@/lib/utils/sectorMetrics';

describe('calculateAverage', () => {
    it('promedia el primer alias disponible de cada empresa', () => {
        const out = calculateAverage([{ roeTTM: 20 }, { roe: 10 }, { roeTTM: 30, roe: 99 }], ['roeTTM', 'roe']);
        expect(out).toBeCloseTo(20); // (20 + 10 + 30) / 3; el 99 no entra
    });
    it('con unidad «percent» divide entre 100 (contrato explícito por campo)', () => {
        expect(calculateAverage([{ m: 20 }, { m: 10 }], ['m'], 'percent')).toBeCloseTo(0.15);
    });
    it('acepta strings numéricos y descarta vacíos, nulos y no finitos', () => {
        const out = calculateAverage(
            [{ m: '10' }, { m: '' }, { m: null }, { m: 'abc' }, { m: undefined }],
            ['m'],
        );
        expect(out).toBe(10);
    });
    it('sin ningún dato válido devuelve null (desconocido honesto)', () => {
        expect(calculateAverage([{ otra: 5 }], ['m'])).toBeNull();
        expect(calculateAverage([], ['m'])).toBeNull();
    });
});

describe('normalizeGrowthScore', () => {
    it.each([
        [0.25, 90], [0.17, 80], [0.12, 70], [0.07, 60], [0.02, 50], [0, 30], [-0.1, 30],
    ])('crecimiento %f → %i', (g, s) => {
        expect(normalizeGrowthScore(g)).toBe(s);
    });
});

describe('normalizeProfitabilityScore', () => {
    it('suma bandas de margen, ROE y ROA con tope 100', () => {
        expect(normalizeProfitabilityScore(0.25, 0.25, 0.15)).toBe(100); // 35+35+30
        expect(normalizeProfitabilityScore(0.06, 0.06, 0.06)).toBe(65);  // 20+20+25
    });
    it('una métrica negativa no suma en su banda', () => {
        expect(normalizeProfitabilityScore(-0.1, 0.25, 0.15)).toBe(65); // 0+35+30
    });
});

describe('normalizeValueScore', () => {
    it('múltiplos bajos puntúan más; no positivos no puntúan', () => {
        expect(normalizeValueScore(10, 1, 2)).toBe(100); // 35+35+30
        expect(normalizeValueScore(30, 5, 4)).toBe(75);   // pe<35→25, pb<6→25, ps<6→25
        expect(normalizeValueScore(0, -1, 0)).toBe(0);
    });
});

describe('normalizeDebtScore', () => {
    it('D/E bajo y current ratio alto puntúan más; D/E usa valor absoluto', () => {
        expect(normalizeDebtScore(0.3, 3)).toBe(70);   // 40+30
        expect(normalizeDebtScore(-0.3, 3)).toBe(70);  // mismo con D/E negativo
        expect(normalizeDebtScore(4, 0.5)).toBe(25);   // 15+10
    });
});

describe('computeComparableCategoryScores', () => {
    const completo = {
        pe: 10, pb: 1, ps: 2, revenueGrowth: 0.25, netMargin: 0.25,
        roe: 0.25, roa: 0.15, debtToEquity: 0.3, currentRatio: 3,
    };
    it('con todas las métricas da scores de categoría calculados', () => {
        expect(computeComparableCategoryScores(completo)).toEqual({
            value: 100, growth: 90, profitability: 100,
            cashFlow: null, momentum: null, debtLiquidity: 70,
        });
    });
    it('cashFlow y momentum son siempre null (sin datos sectoriales)', () => {
        const s = computeComparableCategoryScores(completo);
        expect(s.cashFlow).toBeNull();
        expect(s.momentum).toBeNull();
    });
    it('si falta una métrica de la categoría, la categoría queda null: no inventa empates', () => {
        expect(computeComparableCategoryScores({ ...completo, ps: null }).value).toBeNull();
        expect(computeComparableCategoryScores({ ...completo, roe: null }).profitability).toBeNull();
        expect(computeComparableCategoryScores({ ...completo, revenueGrowth: null }).growth).toBeNull();
        expect(computeComparableCategoryScores({ ...completo, currentRatio: null }).debtLiquidity).toBeNull();
    });
});
