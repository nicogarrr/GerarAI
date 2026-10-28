import { describe, expect, it } from 'vitest';
import { formatNumberForInput, parseLocalizedNumberDetailed } from '@/lib/format';

describe('formatNumberForInput', () => {
    it('escribe decimales con coma es-ES y enteros tal cual', () => {
        expect(formatNumberForInput(10)).toBe('10');
        expect(formatNumberForInput(2.5)).toBe('2,5');
        expect(formatNumberForInput(6.0572)).toBe('6,0572');
        expect(formatNumberForInput(150.5)).toBe('150,5');
    });

    it('nunca devuelve notación científica ni símbolos que el parser rechaza', () => {
        for (const n of [1e-7, 1e21, 0.0000001, 123456789.123456]) {
            const text = formatNumberForInput(n);
            expect(text).not.toMatch(/[eE∞]/);
            expect(parseLocalizedNumberDetailed(text).ok).toBe(true);
        }
    });

    it('round-trip: guardar sin tocar conserva el valor práctico', () => {
        for (const n of [0, 4, 2.5, 6.0572, 150.5, 1234.5, 0.0000001, 0.3]) {
            const parsed = parseLocalizedNumberDetailed(formatNumberForInput(n));
            expect(parsed.ok).toBe(true);
            if (parsed.ok) expect(Math.abs(parsed.value - n)).toBeLessThan(1e-9);
        }
    });

    it('no finito queda vacío (sin «Infinity» ni «NaN» en el input)', () => {
        expect(formatNumberForInput(Number.POSITIVE_INFINITY)).toBe('');
        expect(formatNumberForInput(Number.NaN)).toBe('');
    });
});
