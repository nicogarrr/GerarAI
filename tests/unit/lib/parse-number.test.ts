import { describe, expect, it } from 'vitest';
import { parseLocalizedNumber, parseLocalizedNumberDetailed } from '@/lib/i18n/parse-number';

describe('parseLocalizedNumber es-ES (locale "es", default)', () => {
    it.each([
        ['32,5', 32.5], ['1.234,56', 1234.56], ['12.345.678,9', 12345678.9],
        ['1.234', 1234], ['1.234.567', 1234567], ['1234.56', 1234.56], ['32.5', 32.5],
        [',5', 0.5], ['.5', 0.5], ['5.', 5], ['0,001', 0.001], ['-1.234,56', -1234.56],
        ['1234', 1234], ['-42', -42],
    ])('acepta %s como %d', (input, expected) => {
        expect(parseLocalizedNumber(input)).toBe(expected);
        expect(parseLocalizedNumber(input, 'es-ES')).toBe(expected);
    });
    it.each(['1,234', '1,234.5', '12.34,5', '1..2', '']) ('rechaza %s como ambigua o vacía', (input) => {
        expect(parseLocalizedNumber(input)).toBeNull();
    });
    it.each(['1e3', '0x10', '1 000', 'Infinity', 'abc', '+3', '-'])('rechaza %s como inválida', (input) => {
        expect(parseLocalizedNumber(input)).toBeNull();
    });
    it('distingue empty, invalid y ambiguous', () => {
        expect(parseLocalizedNumberDetailed('', 'es')).toEqual({ ok: false, error: 'empty' });
        expect(parseLocalizedNumberDetailed('abc', 'es')).toEqual({ ok: false, error: 'invalid' });
        expect(parseLocalizedNumberDetailed('1,234', 'es')).toEqual({ ok: false, error: 'ambiguous' });
    });
});

describe('parseLocalizedNumber en-US (locale "en")', () => {
    it.each([
        ['1,234.56', 1234.56], ['1,234', 1234], ['1,234,567', 1234567], ['12,345,678.9', 12345678.9],
        ['32.5', 32.5], ['1234.56', 1234.56], ['1234', 1234], ['.5', 0.5], ['5.', 5],
        ['0.001', 0.001], ['-1,234.56', -1234.56], ['-42', -42], ['1.2345', 1.2345],
    ])('acepta %s como %d', (input, expected) => {
        expect(parseLocalizedNumber(input, 'en')).toBe(expected);
        expect(parseLocalizedNumber(input, 'en-US')).toBe(expected);
    });
    it.each([
        // Ambiguas en en-US: ¿decimal US o miles es-ES?
        '1.234', '12.345',
        // Gramática es-ES en locale en-US
        '1.234,56', '1.234.567', ',5', '32,5',
        // Grupos de miles rotos
        '12,34', '12,34.5', '1,23,456',
        // Basura sintáctica
        '1.2.3', '1..2', '.', '5,', '1,,2',
    ])('rechaza %s como ambigua', (input) => {
        expect(parseLocalizedNumber(input, 'en')).toBeNull();
    });
    it.each(['1e3', '0x10', '1 000', 'Infinity', 'abc', '+3', '-'])('rechaza %s como inválida', (input) => {
        expect(parseLocalizedNumber(input, 'en')).toBeNull();
    });
    it('distingue empty, invalid y ambiguous', () => {
        expect(parseLocalizedNumberDetailed('  ', 'en')).toEqual({ ok: false, error: 'empty' });
        expect(parseLocalizedNumberDetailed('abc', 'en')).toEqual({ ok: false, error: 'invalid' });
        expect(parseLocalizedNumberDetailed('1.234', 'en')).toEqual({ ok: false, error: 'ambiguous' });
    });
});
