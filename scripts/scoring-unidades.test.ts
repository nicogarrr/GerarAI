/**
 * Test: unidades del scoring avanzado (Finnhub /stock/metric y /quote).
 *
 * Finnhub da márgenes, ROE, ROA y crecimientos en PORCENTAJE (24,3 = 24,3 %) y
 * `quote.dp` también en porcentaje («Percent change»). Antes:
 *  - la heurística |x| > 1 ⇒ % leía un margen del 0,8 % como 80 %;
 *  - un crecimiento > 100 % se dividía dos veces por 100 (150 % → 1,5 %);
 *  - dp/100 se comparaba con umbrales 1 y 2 ⇒ siempre +5 puntos.
 *
 * Ejecución: node --experimental-strip-types --test scripts/scoring-unidades.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
    dailyChangePoints,
    ebitdaGrowthPoints,
    epsGrowthPoints,
    netMarginPoints,
    percentToRatio,
    revenueGrowthPoints,
    roaPoints,
    roePoints,
    // @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
} from '../lib/utils/profitabilityPoints.ts';

describe('scoring avanzado: unidades de Finnhub (porcentaje)', () => {
    it('percentToRatio divide SIEMPRE entre 100 (sin heurística |x| > 1)', () => {
        assert.equal(percentToRatio(0.8), 0.008);
        assert.equal(percentToRatio(24.3), 0.243);
        assert.equal(percentToRatio(150), 1.5);
    });

    it('un margen del 0,8 % es un margen pequeño, no uno del 80 %', () => {
        // 0,8 % = 0,008 > 0 pero < 10 % → 15 puntos (antes 35: lo leía como 80 % > 1,3 × 15 %).
        assert.equal(netMarginPoints(0.8, 0.15), 15);
    });

    it('ROE 0,9 % y ROA 0,5 % puntúan como rentabilidad baja', () => {
        // ROE 0,009 → (0, 10 %] → 20 (antes 35); ROA 0,005 → (0, 5 %] → 20 (antes 30).
        assert.equal(roePoints(0.9), 20);
        assert.equal(roaPoints(0.5), 20);
        // ROE 150 % sigue siendo el tramo máximo.
        assert.equal(roePoints(150), 35);
    });

    it('un crecimiento de ventas del 150 % es 1,5 (no 0,015)', () => {
        // Sector 15 %: 1,5 > 1,5 × 0,15 = 0,225 → 40 (antes 25: 150/100/100 = 0,015).
        assert.equal(revenueGrowthPoints(150, 0.15), 40);
        assert.equal(revenueGrowthPoints(20, 0.15), 35); // 0,20 ∈ (0,15; 0,225]
        assert.equal(revenueGrowthPoints(-5, 0.15), 10);
    });

    it('crecimiento de BPA 120 % y de EBITDA 250 % en el tramo alto', () => {
        assert.equal(epsGrowthPoints(120), 30); // 1,2 > 0,2 (antes 0,012 → 20)
        assert.equal(epsGrowthPoints(15), 25);
        assert.equal(ebitdaGrowthPoints(250), 30); // 2,5 > 0,15 (antes 0,025 → 20)
        assert.equal(ebitdaGrowthPoints(-3), 10);
    });

    it('el cambio diario (dp en %) puntúa con signo y en las unidades correctas', () => {
        assert.equal(dailyChangePoints(2.5), 15); // +2,5 % (antes 5: 0,025 nunca > 2)
        assert.equal(dailyChangePoints(1.5), 10);
        assert.equal(dailyChangePoints(0.4), 5);
        // Una caída fuerte no premia impulso (antes |−3 %| contaba como volatilidad).
        assert.equal(dailyChangePoints(-3), 5);
    });
});
