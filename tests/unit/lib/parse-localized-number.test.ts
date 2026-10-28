import { describe, expect, it } from 'vitest';
import { parseLocalizedNumber, parseLocalizedNumberDetailed } from '@/lib/format';

describe('parseLocalizedNumberDetailed: formato es-ES válido', () => {
    it.each([
        ['32,5', 32.5],
        ['1.234,5', 1234.5],
        ['1.234,56', 1234.56],
        ['12.345.678,9', 12345678.9],
        ['0,001', 0.001],
        [',5', 0.5],
        ['1234', 1234],
        ['0', 0],
        ['1.234', 1234], // miles es-ES
        ['1.234.567', 1234567],
        ['32.5', 32.5], // decimal con punto (sin agrupación de 3)
        ['1.23', 1.23],
        ['1.2345', 1.2345],
        ['.5', 0.5],
        ['-32,5', -32.5],
        ['-1.234,5', -1234.5],
        ['-1.234', -1234],
    ])('parsea %s como %d', (input, expected) => {
        expect(parseLocalizedNumberDetailed(input)).toEqual({ ok: true, value: expected });
    });
});

describe('parseLocalizedNumberDetailed: formatos ambiguos rechazados (nunca reinterpretados)', () => {
    it.each([
        '1,234.5', // orden US mezclado: antes se leía 1,2345 (factor 1000 en dinero)
        '1,234', // ¿1,234 es-ES o 1234 US?
        '12,500', // misma ambigüedad con otro entero
        '12.34,5', // grupo de miles roto
        '1,2,3',
        '1.2.3',
        '1..2',
        '32,',
        '1,2e3',
        '1.234.567,89.0',
    ])('rechaza %s como ambiguo', (input) => {
        expect(parseLocalizedNumberDetailed(input)).toEqual({ ok: false, error: 'ambiguous' });
    });
});

describe('parseLocalizedNumberDetailed: entradas inválidas rechazadas', () => {
    it.each([
        '1e3', // Number() lo aceptaba como 1000 en silencio
        '-1e3',
        '0x10',
        'Infinity',
        '-Infinity',
        'abc',
        '1 000',
        '+3',
        '-',
        '1.2.3.4.5,6,7',
    ])('rechaza %s', (input) => {
        const result = parseLocalizedNumberDetailed(input);
        expect(result.ok).toBe(false);
    });
    it('vacío o blancos es empty', () => {
        expect(parseLocalizedNumberDetailed('')).toEqual({ ok: false, error: 'empty' });
        expect(parseLocalizedNumberDetailed('   ')).toEqual({ ok: false, error: 'empty' });
    });
});

describe('parseLocalizedNumber (wrapper): null ante vacío, inválido o ambiguo', () => {
    it('valores válidos', () => {
        expect(parseLocalizedNumber('32,5')).toBe(32.5);
        expect(parseLocalizedNumber('1.234,56')).toBe(1234.56);
        expect(parseLocalizedNumber('-1.234')).toBe(-1234);
    });
    it.each(['1,234.5', '1,234', '1e3', 'abc', '', '12.34,5'])('null para %s', (input) => {
        expect(parseLocalizedNumber(input)).toBeNull();
    });
});
