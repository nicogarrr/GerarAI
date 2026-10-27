import { describe, expect, it } from 'vitest';
import {
    coerceInvalidationRules, describeInvalidationRule, formatThresholdEs, invalidationMetricLabel, isPercentMetric, parseThreshold,
} from '@/lib/research/thesis-invalidation-rules';

describe('parseThreshold', () => {
    it('acepta coma decimal, signo menos Unicode y espacios', () => {
        expect(parseThreshold('-10,5')).toBe(-10.5);
        expect(parseThreshold('\u221210')).toBe(-10);
        expect(parseThreshold(' 1 000 ')).toBe(1000);
        expect(parseThreshold('+3')).toBe(3);
    });
    it('rechaza lo ambiguo en vez de adivinar', () => {
        for (const raw of ['', 'abc', '1.234,56', '1e3', '--1', '10%', '.5', '5.']) expect(parseThreshold(raw)).toBeNull();
    });
});

describe('metric helpers', () => {
    it('isPercentMetric solo para métricas porcentuales declaradas', () => {
        expect(isPercentMetric('margen_seguridad_pct')).toBe(true);
        expect(isPercentMetric('precio')).toBe(false);
        expect(isPercentMetric('metrica:roic')).toBe(false);
    });
    it('etiquetas: conocida, personalizada y desconocida', () => {
        expect(invalidationMetricLabel('margen_seguridad_pct')).toBe('margen de seguridad');
        expect(invalidationMetricLabel('metrica: roic ')).toBe('roic');
        expect(invalidationMetricLabel('otra')).toBe('otra');
    });
    it('formatThresholdEs', () => {
        expect(formatThresholdEs(-10, true)).toBe('-10,00 %');
        expect(formatThresholdEs(1234.5, false)).toBe('1234,50');
    });
});

describe('describeInvalidationRule', () => {
    it('símbolos matemáticos y % solo en métricas porcentuales', () => {
        expect(describeInvalidationRule({ metric: 'margen_seguridad_pct', operator: '<=', threshold: -10 })).toBe('margen de seguridad ≤ -10,00 %');
        expect(describeInvalidationRule({ metric: 'precio', operator: '!=', threshold: 5 })).toBe('precio ≠ 5,00');
    });
});

describe('coerceInvalidationRules', () => {
    it('no-array -> []', () => {
        expect(coerceInvalidationRules(null)).toEqual([]);
        expect(coerceInvalidationRules({})).toEqual([]);
    });
    it('descarta reglas inválidas, convierte umbrales en texto, mantiene las buenas', () => {
        const out = coerceInvalidationRules([
            { metric: 'precio', operator: '<', threshold: '10,5', description: 'd' },
            { metric: 'precio', operator: '<<', threshold: 1 },
            { metric: 'precio', operator: '<', threshold: 'x' },
            { metric: 5, operator: '<', threshold: 1 },
            null, 'x',
            { metric: 'metrica:roic', operator: '>=', threshold: 0.08, description: 7 },
        ]);
        expect(out).toEqual([
            { metric: 'precio', operator: '<', threshold: 10.5, description: 'd' },
            { metric: 'metrica:roic', operator: '>=', threshold: 0.08, description: null },
        ]);
    });
    it('umbral numérico NaN/ausente no pasa a regla con NaN', () => {
        const out = coerceInvalidationRules([{ metric: 'precio', operator: '<' }, { metric: 'precio', operator: '<', threshold: '' }]);
        expect(out).toEqual([]);
    });
});
