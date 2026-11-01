import { describe, expect, it } from 'vitest';
import { formatNumberForInput, parseLocalizedNumberDetailed } from '@/lib/format';
import { parseLocalizedNumberDetailed as parseForLocale } from '@/lib/i18n/parse-number';

// Editar una operación de 1,234 acciones o un precio de 12,345 €: el valor se
// escribe en el input y al guardar se relee. Con justo 3 decimales el texto
// («1,234») era «ambiguo» para el parser y el formulario no dejaba guardar.
const VALUES = [1.234, 12.345, -2.125, 999.999, 1234.567, 0.125, 0.001, 2.5, 1000];

describe('formatNumberForInput: 3 decimales se releen igual', () => {
    it.each(VALUES)('es: %s', (n) => {
        const text = formatNumberForInput(n);
        for (const parsed of [parseLocalizedNumberDetailed(text), parseForLocale(text, 'es')]) {
            expect(parsed.ok).toBe(true);
            if (parsed.ok) expect(Math.abs(parsed.value - n)).toBeLessThan(1e-9);
        }
    });

    it.each(VALUES)('en: %s', (n) => {
        const text = formatNumberForInput(n, 'en');
        const parsed = parseForLocale(text, 'en');
        expect(parsed.ok).toBe(true);
        if (parsed.ok) expect(Math.abs(parsed.value - n)).toBeLessThan(1e-9);
    });

    it('solo añade el 0 donde hace falta', () => {
        expect(formatNumberForInput(1.234)).toBe('1,2340');
        expect(formatNumberForInput(0.125)).toBe('0,125');
        expect(formatNumberForInput(2.5)).toBe('2,5');
        expect(formatNumberForInput(1000)).toBe('1000');
    });
});
