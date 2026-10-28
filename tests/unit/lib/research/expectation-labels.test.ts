import { describe, expect, it } from 'vitest';
import { expectationMetricLabel, reviewStatusLabel } from '@/lib/research/expectation-labels';

describe('etiquetas de expectativas', () => {
    it('estado: vacío s/d, conocido en español, desconocido tal cual', () => {
        expect(reviewStatusLabel(null)).toBe('s/d');
        expect(reviewStatusLabel('')).toBe('s/d');
        expect(reviewStatusLabel('outside_tolerance')).toBe('fuera de tolerancia');
        expect(reviewStatusLabel('algo_nuevo')).toBe('algo_nuevo');
    });
    it('métrica: vacío s/d, conocida, desconocida humanizada', () => {
        expect(expectationMetricLabel(undefined)).toBe('s/d');
        expect(expectationMetricLabel('free_cash_flow')).toBe('Flujo de caja libre');
        expect(expectationMetricLabel('nueva_metrica_x')).toBe('nueva metrica x');
    });
});
