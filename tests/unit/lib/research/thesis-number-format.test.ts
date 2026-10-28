// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { thesisEps, thesisMoney } from '@/lib/research/thesis-number-format';

describe('thesisMoney', () => {
    it('USD en formato en-US; el resto es-ES', () => {
        expect(thesisMoney(1234.5, 'USD')).toBe('$1,234.50');
        expect(thesisMoney(1234.5, 'EUR')).toBe('1.234,50 €');
    });
});

describe('thesisEps', () => {
    it('sin base de acciones/divisa no infiere símbolo: número en-US a 2 decimales', () => {
        expect(thesisEps(1.234)).toBe('1.23');
    });
    it('null/undefined/NaN: N/D', () => {
        expect(thesisEps(null)).toBe('N/D');
        expect(thesisEps(undefined)).toBe('N/D');
        expect(thesisEps(NaN)).toBe('N/D');
    });
});
