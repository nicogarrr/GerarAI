// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    dailyChangePoints, ebitdaGrowthPoints, epsGrowthPoints, netMarginPoints,
    percentToRatio, revenueGrowthPoints, roaPoints, roePoints,
} from '@/lib/utils/profitabilityPoints';

describe('percentToRatio', () => {
    it('divide siempre entre 100 conservando el signo (Finnhub da %)', () => {
        expect(percentToRatio(24.3)).toBeCloseTo(0.243);
        expect(percentToRatio(-15)).toBeCloseTo(-0.15);
        expect(percentToRatio(150)).toBeCloseTo(1.5); // ROE de Apple: 150 % = 1.5, no 0.015
    });
});

describe('netMarginPoints', () => {
    it('sin benchmark sectorial puntúa por bandas absolutas', () => {
        expect(netMarginPoints(25, null)).toBe(25);
        expect(netMarginPoints(5, null)).toBe(15);
        expect(netMarginPoints(-5, null)).toBe(0); // una pérdida no es rentabilidad
    });
    it('con sector positivo: supera x1,3 → 35; supera al sector → 30', () => {
        expect(netMarginPoints(20, 0.1)).toBe(35); // 0.20 > 0.13
        expect(netMarginPoints(12, 0.1)).toBe(30);
        expect(netMarginPoints(8, 0.1)).toBe(15);   // por debajo: banda absoluta
    });
    it('con sector en pérdidas NO premia perder igual o más que el sector (V6)', () => {
        // Antes: -0.15 > -0.10 * 1.3 = -0.13 daba el máximo.
        expect(netMarginPoints(-15, -0.1)).toBe(0);
        expect(netMarginPoints(-5, -0.1)).toBe(30);  // menos mala que el sector: tramo intermedio
        expect(netMarginPoints(12, -0.1)).toBe(35);  // claramente positiva y por encima
    });
});

describe('roePoints / roaPoints', () => {
    it.each([
        [25, 35], [18, 30], [12, 25], [5, 20], [-10, 10],
    ])('ROE %i %% → %i puntos', (roe, puntos) => {
        expect(roePoints(roe)).toBe(puntos);
    });
    it.each([
        [12, 30], [7, 25], [2, 20], [-3, 10],
    ])('ROA %i %% → %i puntos', (roa, puntos) => {
        expect(roaPoints(roa)).toBe(puntos);
    });
});

describe('revenueGrowthPoints', () => {
    it('sin sector: crece → 25, no crece → 10', () => {
        expect(revenueGrowthPoints(5, null)).toBe(25);
        expect(revenueGrowthPoints(0, null)).toBe(10);
        expect(revenueGrowthPoints(-8, null)).toBe(10);
    });
    it('con sector positivo: x1,5 → 40, supera → 35', () => {
        expect(revenueGrowthPoints(20, 0.1)).toBe(40);
        expect(revenueGrowthPoints(12, 0.1)).toBe(35);
        expect(revenueGrowthPoints(5, 0.1)).toBe(25);
    });
    it('con sector en contracción no da el máximo por caer menos (V6)', () => {
        expect(revenueGrowthPoints(-12, -0.1)).toBe(10); // -0.12 no es fuerza
        expect(revenueGrowthPoints(-5, -0.1)).toBe(35);  // supera al sector: tramo intermedio
        expect(revenueGrowthPoints(15, -0.1)).toBe(40);  // crece de verdad
    });
});

describe('epsGrowthPoints / ebitdaGrowthPoints', () => {
    it.each([[25, 30], [12, 25], [3, 20], [-5, 10]])('EPS growth %i %% → %i', (g, p) => {
        expect(epsGrowthPoints(g)).toBe(p);
    });
    it.each([[20, 30], [5, 20], [-5, 10]])('EBITDA growth %i %% → %i', (g, p) => {
        expect(ebitdaGrowthPoints(g)).toBe(p);
    });
});

describe('dailyChangePoints', () => {
    it('umbrales +1 %% / +2 %% con signo: una caída fuerte no es impulso', () => {
        expect(dailyChangePoints(3)).toBe(15);
        expect(dailyChangePoints(1.5)).toBe(10);
        expect(dailyChangePoints(0.5)).toBe(5);
        expect(dailyChangePoints(-9)).toBe(5);
    });
});
