import { describe, expect, it } from 'vitest';

import { checkSpanishTaxId, spanishTaxIdWarning } from '@/lib/nif';

describe('checkSpanishTaxId', () => {
  it('vacío o blancos: sin aviso', () => {
    expect(checkSpanishTaxId('')).toBe('empty');
    expect(checkSpanishTaxId('   ')).toBe('empty');
    expect(spanishTaxIdWarning('')).toBeNull();
  });

  it('DNI válido con su letra de control', () => {
    expect(checkSpanishTaxId('12345678Z')).toBe('valid'); // 12345678 % 23 = 14 -> Z
    expect(checkSpanishTaxId('00000000T')).toBe('valid'); // 0 % 23 = 0 -> T
  });

  it('DNI con letra errónea: bad_control', () => {
    expect(checkSpanishTaxId('12345678A')).toBe('bad_control');
    expect(spanishTaxIdWarning('12345678A')).toContain('dígito de control');
  });

  it('DNI tolera minúsculas, espacios, puntos y guiones', () => {
    expect(checkSpanishTaxId('12.345.678-z')).toBe('valid');
    expect(checkSpanishTaxId(' 12345678z ')).toBe('valid');
  });

  it('NIE válido (X/Y/Z con prefijo numérico)', () => {
    expect(checkSpanishTaxId('X1234567L')).toBe('valid'); // 01234567 % 23 = 19 -> L
    expect(checkSpanishTaxId('Y1234567X')).toBe('valid'); // 11234567 % 23 = 10 -> X
    expect(checkSpanishTaxId('Z1234567R')).toBe('valid'); // 21234567 % 23 = 1 -> R
  });

  it('NIE con letra errónea: bad_control', () => {
    expect(checkSpanishTaxId('X1234567A')).toBe('bad_control');
  });

  it('CIF válido con control numérico (A/B/E/H)', () => {
        expect(checkSpanishTaxId('A58818501')).toBe('valid');
    expect(checkSpanishTaxId('B85372571')).toBe('valid');
  });

  it('CIF válido con control alfabético (N/P/Q/R/S/W)', () => {
    expect(checkSpanishTaxId('Q2826000H')).toBe('valid');
    expect(checkSpanishTaxId('S4639210F')).toBe('valid');
  });

  it('CIF con control erróneo: bad_control', () => {
    expect(checkSpanishTaxId('A58818502')).toBe('bad_control');
    expect(checkSpanishTaxId('Q2826000J')).toBe('bad_control');
  });

  it('formato no español: unknown_format con aviso no bloqueante', () => {
    expect(checkSpanishTaxId('DE123456789')).toBe('unknown_format');
    expect(checkSpanishTaxId('12345')).toBe('unknown_format');
    const warning = spanishTaxIdWarning('DE123456789');
    expect(warning).toContain('extranjero');
    expect(warning).toContain('ignorar este aviso');
  });
});
