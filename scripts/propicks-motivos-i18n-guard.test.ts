/**
 * Guard i18n de los motivos ProPicks (bug QA 2026-10-19, visto en prod):
 * «Ingresos creciendo al 50.2% anual (5 anos)» mezclaba decimal inglés y
 * «anos» sin tilde; «...superados segun fundamentales auditados» sin tilde.
 * La UI es en castellano (regla de la app: texto visible en es-ES, decimales
 * con coma) y R2 exige que el valor siga visible en el texto, así que el
 * validador acepta el formato es-ES como variante verificable.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-motivos-i18n-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    validateReasonsTraceable,
    valueTextVariants,
    type PickLike,
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
} from '../lib/utils/propicksValidation.ts';

const funnel = readFileSync('lib/actions/propicks-funnel.actions.ts', 'utf8');

describe('ProPicks: motivos en castellano es-ES', () => {
    it('los textos de motivos no llevan «anos» sin tilde ni «segun» sin tilde', () => {
        assert.ok(!/\(5 anos\)/.test(funnel), 'queda «(5 anos)» sin tilde en los motivos');
        assert.ok(!/segun fundamentales/.test(funnel), 'queda «segun» sin tilde en los motivos');
    });

    it('los porcentajes de los motivos se componen con formato es-ES (coma decimal)', () => {
        for (const rawInterpolation of [
            /\$\{facts\['revenue_cagr'\]\}%/,
            /\$\{facts\['fcf_margin_5y'\]\}%/,
            /\$\{facts\['cfroi_approx'\]\}%/,
            /spread de \$\{spread\}/,
        ]) {
            assert.ok(!rawInterpolation.test(funnel), `queda una cifra sin formato es-ES: ${rawInterpolation}`);
        }
    });

    it('R2 acepta el valor en formato es-ES (coma) dentro del texto del motivo', () => {
        const pick: PickLike = {
            symbol: 'TEST',
            asOf: '2026-10-19T09:00:00.000Z',
            facts: { revenue_cagr: 50.2, fcf_margin_5y: 31.3 },
            confidenceReasons: [
                { metric: 'revenue_cagr', value: 50.2, text: 'Ingresos creciendo al 50,2 % anual (5 años)' },
                { metric: 'fcf_margin_5y', value: 31.3, text: 'Margen FCF medio del 31,3 % (5 años)' },
            ],
            score: 80,
            categoryScores: { value: 80, growth: 70, profitability: 90, cashFlow: 60, momentum: 75, debtLiquidity: 65 },
        };
        assert.deepEqual(validateReasonsTraceable(pick), []);
    });

    it('R2 sigue rechazando un texto sin el valor', () => {
        const pick: PickLike = {
            symbol: 'TEST',
            asOf: '2026-10-19T09:00:00.000Z',
            facts: { revenue_cagr: 50.2 },
            confidenceReasons: [
                { metric: 'revenue_cagr', value: 50.2, text: 'Ingresos creciendo con fuerza' },
                { metric: 'revenue_cagr', value: 50.2, text: 'Crecimiento alto' },
            ],
            score: 80,
            categoryScores: { value: 80, growth: 70, profitability: 90, cashFlow: 60, momentum: 75, debtLiquidity: 65 },
        };
        assert.ok(validateReasonsTraceable(pick).length > 0);
    });

    it('valueTextVariants: decimal y miles', () => {
        assert.ok(valueTextVariants(50.2).includes('50,2'));
        assert.ok(valueTextVariants(50.2).includes('50.2'));
        assert.ok(valueTextVariants(12250).includes('12.250'));
        assert.deepEqual(valueTextVariants(100), ['100']);
        assert.deepEqual(valueTextVariants('FY2025'), ['FY2025']);
    });
});
