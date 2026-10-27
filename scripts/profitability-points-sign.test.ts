/**
 * Test: el scoring avanzado conserva el signo de margen neto, ROE y ROA.
 *
 * Ejecución: node --experimental-strip-types --test scripts/profitability-points-sign.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { netMarginPoints, ratioFromProviderValue, roaPoints, roePoints } from '../lib/utils/profitabilityPoints.ts';

describe('profitabilityPoints: signo de la rentabilidad', () => {
    it('convierte % a fracción sin perder el signo', () => {
        assert.equal(ratioFromProviderValue(30), 0.3);
        assert.equal(ratioFromProviderValue(-30), -0.3);
        assert.equal(ratioFromProviderValue(-0.05), -0.05);
    });

    it('un margen neto negativo puntúa 0, no como uno positivo', () => {
        // Sector 15 %: +30 % > 19,5 % → 35 puntos; -30 % es pérdida → 0 puntos.
        assert.equal(netMarginPoints(30, 0.15), 35);
        assert.equal(netMarginPoints(-30, 0.15), 0);
        assert.equal(netMarginPoints(-0.3, 0.15), 0);
    });

    it('ROE y ROA negativos reciben la puntuación mínima', () => {
        assert.equal(roePoints(25), 35);
        assert.equal(roePoints(-25), 10);
        assert.equal(roaPoints(12), 30);
        assert.equal(roaPoints(-12), 10);
    });
});
