/**
 * Valores del screener en es-ES: la coma decimal es válida, los formatos
 * ambiguos («1,234») se rechazan en lugar de reinterpretarse x1000.
 * Regresión: el input type=number impedía escribir la coma y el parser
 * con replace(',', '.') aceptaba «1,234» como 1.234.
 */
import { describe, expect, it } from 'vitest';

import { toBackendValue, fromBackendValue } from '@/lib/screener-metrics';

describe('toBackendValue: gramática es-ES', () => {
    it('coma decimal: «12,5» en % -> 0.125', () => {
        expect(toBackendValue('12,5', 'ratio')).toBe('0.125');
    });
    it('punto decimal también: «12.5» en % -> 0.125', () => {
        expect(toBackendValue('12.5', 'ratio')).toBe('0.125');
    });
    it('miles es-ES: «1.234,56» en número -> 1234.56', () => {
        expect(toBackendValue('1.234,56', 'number')).toBe('1234.56');
    });
    it('ambiguo «1,234»: rechazado (vacío), nunca reinterpretado', () => {
        expect(toBackendValue('1,234', 'number')).toBe('');
    });
    it('texto inválido: vacío', () => {
        expect(toBackendValue('abc', 'number')).toBe('');
        expect(toBackendValue('', 'number')).toBe('');
    });
    it('«0,001» es decimal (los miles no empiezan por 0)', () => {
        expect(toBackendValue('0,001', 'number')).toBe('0.001');
    });
});

describe('fromBackendValue: inverso intacto', () => {
    it('0.15 en % -> 15', () => {
        expect(fromBackendValue('0.15', 'ratio')).toBe('15');
    });
});
