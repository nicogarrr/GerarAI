import { describe, expect, it } from 'vitest';
import { metricLabel } from '@/lib/research/metric-labels';

describe('metricLabel', () => {
    it('traduce las acciones en circulación (la tabla «Números» de POOL mostraba «shares outstanding»)', () => {
        expect(metricLabel('shares_outstanding')).toBe('Acciones en circulación');
        expect(metricLabel('shares outstanding')).toBe('Acciones en circulación');
        expect(metricLabel('SHARES_OUTSTANDING')).toBe('Acciones en circulación');
    });

    it('mantiene las etiquetas vecinas y el respaldo humanizado', () => {
        expect(metricLabel('shares_diluted')).toBe('Acciones diluidas (media)');
        expect(metricLabel('clave_nueva_backend')).toBe('clave nueva backend');
    });
});
