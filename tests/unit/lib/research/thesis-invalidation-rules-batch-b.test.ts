// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    coerceInvalidationRules, describeInvalidationRule, formatThresholdEs,
    invalidationMetricLabel, isPercentMetric, parseThreshold,
} from '@/lib/research/thesis-invalidation-rules';

describe('isPercentMetric / invalidationMetricLabel', () => {
    it('solo las métricas marcadas son porcentuales', () => {
        expect(isPercentMetric('margen_seguridad_pct')).toBe(true);
        expect(isPercentMetric('variacion_desde_tesis_pct')).toBe(true);
        expect(isPercentMetric('precio')).toBe(false);
        expect(isPercentMetric('metrica:roic')).toBe(false);
    });
    it('una métrica personalizada muestra su nombre sin el prefijo', () => {
        expect(invalidationMetricLabel('metrica:roic')).toBe('roic');
    });
    it('las conocidas se muestran en minúscula sin «(%)»; desconocidas crudas', () => {
        expect(invalidationMetricLabel('margen_seguridad_pct')).toBe('margen de seguridad');
        expect(invalidationMetricLabel('precio')).toBe('precio');
        expect(invalidationMetricLabel('otra_metrica')).toBe('otra_metrica');
    });
});

describe('formatThresholdEs', () => {
    it('formato es-ES con 2 decimales; % solo en métricas porcentuales', () => {
        expect(formatThresholdEs(-10.5, true)).toBe('-10,50 %');
        expect(formatThresholdEs(0.08, false)).toBe('0,08');
    });
});

describe('describeInvalidationRule', () => {
    it('describe la regla en español con operador tipográfico', () => {
        expect(describeInvalidationRule({ metric: 'margen_seguridad_pct', operator: '<', threshold: -10 }))
            .toBe('margen de seguridad < -10,00 %');
        expect(describeInvalidationRule({ metric: 'precio', operator: '>=', threshold: 100 }))
            .toBe('precio ≥ 100,00');
    });
});

describe('parseThreshold', () => {
    it.each([
        ['coma decimal', '-10,5', -10.5],
        ['punto decimal', '0.08', 0.08],
        ['menos tipográfico U+2212', '\u221210', -10],
        ['espacios', ' 1 000,5 ', 1000.5],
        ['signo +', '+3', 3],
    ])('acepta %s', (_e, raw, expected) => {
        expect(parseThreshold(raw)).toBe(expected);
    });
    it.each(['abc', '', '1.2.3', '--5', '10%'])('rechaza %s', (raw) => {
        expect(parseThreshold(raw)).toBeNull();
    });
});

describe('coerceInvalidationRules', () => {
    it('normaliza la lista de la API y descarta lo inválido', () => {
        const out = coerceInvalidationRules([
            { metric: 'precio', operator: '<', threshold: 100 },
            { metric: 'precio', operator: '>=', threshold: '-10,5' }, // umbral como string
            { metric: 'precio', operator: '==', threshold: 5, description: 'nota' },
            { metric: 'precio', operator: '>>', threshold: 5 },        // operador inválido
            { metric: 5, operator: '<', threshold: 5 },                // métrica no string
            { metric: 'precio', operator: '<', threshold: 'abc' },     // umbral no numérico
            null,
            'ruido',
        ]);
        expect(out).toEqual([
            { metric: 'precio', operator: '<', threshold: 100, description: null },
            { metric: 'precio', operator: '>=', threshold: -10.5, description: null },
            { metric: 'precio', operator: '==', threshold: 5, description: 'nota' },
        ]);
    });
    it('entrada no lista: []', () => {
        expect(coerceInvalidationRules(undefined)).toEqual([]);
        expect(coerceInvalidationRules('reglas')).toEqual([]);
    });
});
