/**
 * Test: comparaciones y puntos honestos del scorer (V4, V5, V6, V7).
 *
 * V4: sin media real del sector, los textos no dicen «vs sector» con un
 *     benchmark inventado (25 / 1.5).
 * V5: un P/FCF negativo (FCF negativo) no recibe los 30 puntos de caja del
 *     fallback `priceToFcf < 15`.
 * V6: con benchmark en pérdidas/contracción, los multiplicadores relativos
 *     no premian perder igual o más que el sector.
 * V7: `vsSector` resta scores de la MISMA fórmula y el mismo conjunto de
 *     métricas en ambos lados.
 *
 * Ejecución: node --experimental-strip-types --test scripts/scorer-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { netMarginPoints, revenueGrowthPoints } from '../lib/utils/profitabilityPoints.ts';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { computeComparableCategoryScores, normalizeValueScore } from '../lib/utils/sectorMetrics.ts';

describe('V6: benchmark negativo no invierte los multiplicadores', () => {
    it('margen -10 % igual al sector (-10 %) no recibe el máximo relativo', () => {
        // Antes: -0,10 > -0,10 * 1,3 = -0,13 → 35 puntos.
        assert.equal(netMarginPoints(-10, -0.1), 0);
    });

    it('margen -15 % PEOR que el sector (-10 %) nunca puntúa por encima', () => {
        // Antes: 35 puntos (máximo relativo).
        assert.equal(netMarginPoints(-15, -0.1), 0);
    });

    it('crecimiento -12 % peor que el sector (-10 %) no recibe el máximo', () => {
        // Antes: -0,12 > -0,10 * 1,5 = -0,15 → 40 puntos.
        assert.equal(revenueGrowthPoints(-12, -0.1), 10);
    });

    it('crecimiento -10 % igual al sector no recibe el máximo', () => {
        assert.equal(revenueGrowthPoints(-10, -0.1), 10);
    });

    it('superar un benchmark en pérdidas con margen claramente positivo sí da el tramo alto', () => {
        assert.equal(netMarginPoints(30, -0.1), 35); // 30 % real y superior al sector
        assert.equal(revenueGrowthPoints(30, -0.1), 40);
    });

    it('benchmark positivo: comportamiento relativo intacto', () => {
        assert.equal(netMarginPoints(30, 0.15), 35);
        assert.equal(netMarginPoints(16, 0.15), 30);
        assert.equal(revenueGrowthPoints(150, 0.15), 40);
        assert.equal(revenueGrowthPoints(20, 0.15), 35);
        assert.equal(revenueGrowthPoints(-5, 0.15), 10);
    });

    it('benchmark cero se trata como no positivo (sin multiplicador)', () => {
        // Contrato existente: (150, 0) → 35 / 40 por vía absoluta+relativa.
        assert.equal(netMarginPoints(150, 0), 35);
        assert.equal(revenueGrowthPoints(150, 0), 40);
    });
});

describe('V7: fórmula común empresa/sector', () => {
    it('métricas iguales a las medias sectoriales dan delta 0, no -15', () => {
        // Repro del audit: PE20/PB3/PS5 en ambos lados.
        const company = computeComparableCategoryScores({
            pe: 20, pb: 3, ps: 5,
            revenueGrowth: 0.10, netMargin: 0.1, roe: 0.1, roa: 0.05,
            debtToEquity: 1, currentRatio: 1.5,
        });
        const sector = computeComparableCategoryScores({
            pe: 20, pb: 3, ps: 5,
            revenueGrowth: 0.10, netMargin: 0.1, roe: 0.1, roa: 0.05,
            debtToEquity: 1, currentRatio: 1.5,
        });
        assert.equal(company.value! - sector.value!, 0);
        assert.equal(company.growth! - sector.growth!, 0);
        assert.equal(company.profitability! - sector.profitability!, 0);
        assert.equal(company.debtLiquidity! - sector.debtLiquidity!, 0);
    });

    it('cashFlow y momentum no tienen datos sectoriales: null honesto', () => {
        const scores = computeComparableCategoryScores({
            pe: 20, pb: 3, ps: 5,
            revenueGrowth: 0.1, netMargin: 0.1, roe: 0.1, roa: 0.05,
            debtToEquity: 1, currentRatio: 1.5,
        });
        assert.equal(scores.cashFlow, null);
        assert.equal(scores.momentum, null);
    });

    it('métrica ausente en un lado: categoría null, no empate inventado', () => {
        const scores = computeComparableCategoryScores({
            pe: 20, pb: null, ps: 5,
            revenueGrowth: null, netMargin: 0.1, roe: null, roa: 0.05,
            debtToEquity: 1, currentRatio: null,
        });
        assert.equal(scores.value, null);
        assert.equal(scores.growth, null);
        assert.equal(scores.profitability, null);
        assert.equal(scores.debtLiquidity, null);
    });

    it('las bandas de valor son las documentadas (normalizeValueScore)', () => {
        assert.equal(normalizeValueScore(20, 3, 5), 85); // 30 + 30 + 25
        assert.equal(normalizeValueScore(10, 1, 2), 100); // 35 + 35 + 30
    });
});

describe('V4/V5: contratos de fuente del scorer', () => {
    const source = readFileSync('lib/utils/advancedStockScoring.ts', 'utf8');

    it('los textos «vs sector» de PER solo salen con media real del sector', () => {
        const peBlock = source.slice(source.indexOf('const realSectorPE'));
        const end = peBlock.indexOf('// PB comparado con sector');
        assert.ok(end > 0);
        const block = peBlock.slice(0, end);
        // Toda mención «vs sector» en el bloque PER va dentro de la guarda real.
        assert.match(block, /if \(realSectorPE !== null\)/);
        assert.doesNotMatch(block, /vs sector.*sectorPE[^S]/);
        assert.match(block, /PER bajo \(\$\{formatNumber\(pe/); // variante absoluta honesta
    });

    it('los textos «vs sector» de deuda solo salen con media real del sector', () => {
        assert.match(source, /const realSectorDte = sectorMetrics\?\.avgDebtToEquity \?\? null/);
        assert.match(source, /Baja deuda \(D\/E:/); // variante absoluta honesta
    });

    it('P/FCF negativo no entra en el fallback de caja y se declara debilidad', () => {
        assert.match(source, /priceToFcf !== null && priceToFcf > 0 && priceToFcf < 15/);
        assert.match(source, /priceToFcf !== null && priceToFcf <= 0/);
        assert.doesNotMatch(source, /priceToFcf && priceToFcf < 15/);
    });

    it('vsSector usa la fórmula común, no los categoryScores de la empresa', () => {
        assert.match(source, /computeComparableCategoryScores\(\{/);
        assert.doesNotMatch(source, /categoryScores\.value - sectorAverages\.value/);
        assert.doesNotMatch(source, /categoryScores\.growth - sectorAverages\.growth/);
    });
});
