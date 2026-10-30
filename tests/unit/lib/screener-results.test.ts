/**
 * Resultados del screener en es-ES (F3): la columna Coincidencia muestra la
 * etiqueta legible de la métrica («Margen bruto») y el operando con formato
 * es-ES («0,4»), nunca el slug técnico ni decimales mezclados es/US.
 */
import { describe, expect, it } from 'vitest';

import {
    formatScreenCriterionRight,
    formatScreenCriterionValue,
    formatScreenRank,
    screenCriterionMetricLabel,
    screenMissingDataEntry,
    screenMissingFieldsLabel,
} from '@/lib/screener-results';

describe('screenCriterionMetricLabel', () => {
    it('métrica conocida -> etiqueta en español', () => {
        expect(screenCriterionMetricLabel('gross_margin')).toBe('Margen bruto');
        expect(screenCriterionMetricLabel('market_cap')).toBe('Capitalización bursátil');
    });
    it('métrica desconocida -> humanizada, nunca snake_case crudo', () => {
        expect(screenCriterionMetricLabel('custom_metric_x')).toBe('custom metric x');
    });
});

describe('formatScreenCriterionRight', () => {
    it('número con punto del backend -> formato es-ES', () => {
        expect(formatScreenCriterionRight('0.4')).toBe('0,4');
    });
    it('nombre de métrica como operando -> etiqueta legible', () => {
        expect(formatScreenCriterionRight('gross_margin')).toBe('Margen bruto');
    });
    it('vacío -> N/D', () => {
        expect(formatScreenCriterionRight('')).toBe('N/D');
        expect(formatScreenCriterionRight(null)).toBe('N/D');
    });
});

describe('screenMissingFieldsLabel', () => {
    it('traduce cada campo y los une', () => {
        expect(screenMissingFieldsLabel(['gross_margin', 'revenue'])).toBe('Margen bruto, Ingresos');
    });
});

describe('regresión: formato de valores existente intacto', () => {
    it('formatScreenCriterionValue sigue dando es-ES', () => {
        expect(formatScreenCriterionValue('0.434')).toBe('0,434');
        expect(formatScreenCriterionValue(null)).toBe('N/D');
    });
    it('formatScreenRank con market_cap compacta', () => {
        expect(formatScreenRank('24000000', 'market_cap')).toBe('24 M');
    });
});

describe('screenMissingDataEntry', () => {
    it('métrica conocida con etiqueta legible y recuento es-ES', () => {
        expect(screenMissingDataEntry('gross_margin', 12, 30)).toBe('Margen bruto (sin dato en 12 de 30 empresas)');
        expect(screenMissingDataEntry('wacc', 3, 30)).toBe('WACC (sin dato en 3 de 30 empresas)');
    });
    it('slug desconocido humanizado, nunca snake_case crudo', () => {
        expect(screenMissingDataEntry('custom_metric_x', 1, 2)).toBe('custom metric x (sin dato en 1 de 2 empresas)');
    });
    it('miles con separador es-ES', () => {
        expect(screenMissingDataEntry('revenue', 1234, 5000)).toBe('Ingresos (sin dato en 1.234 de 5.000 empresas)');
    });
});
