/**
 * formatCountEs: conteos con concordancia singular/plural en es-ES.
 * Regresión de la familia «1 posiciones» / «1 sesiones» / «1 años».
 */
import { describe, expect, it } from 'vitest';

import { formatCountEs } from '@/lib/format';

describe('formatCountEs', () => {
    it('1 usa el singular', () => {
        expect(formatCountEs(1, 'posición', 'posiciones')).toBe('1 posición');
        expect(formatCountEs(1, 'sesión', 'sesiones')).toBe('1 sesión');
        expect(formatCountEs(1, 'año', 'años')).toBe('1 año');
    });
    it('0 y 2+ usan el plural', () => {
        expect(formatCountEs(0, 'mes', 'meses')).toBe('0 meses');
        expect(formatCountEs(2, 'mes', 'meses')).toBe('2 meses');
    });
    it('miles con separador es-ES', () => {
        expect(formatCountEs(12345, 'registro de detalle', 'registros de detalle'))
            .toBe('12.345 registros de detalle');
    });
});
