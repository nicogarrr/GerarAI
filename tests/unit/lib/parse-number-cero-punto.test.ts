import { describe, expect, it } from 'vitest';
import { parseLocalizedNumber as parseI18n } from '@/lib/i18n/parse-number';
import { parseLocalizedNumber as parseFormat } from '@/lib/format';

// Un grupo de miles nunca empieza por 0: «0.125» en un formulario en español
// es 0,125 (un precio de céntimos, escrito con el punto decimal que el parser
// ya admite en «32.5»), no 125. Antes salía 125: un factor 1000 silencioso.
describe.each([
    ['lib/i18n/parse-number', parseI18n],
    ['lib/format', parseFormat],
])('%s es-ES: un 0 delante nunca es grupo de miles', (_name, parse) => {
    it.each([
        ['0.125', 0.125], ['0.001', 0.001], ['-0.250', -0.25], ['0.5', 0.5],
    ])('acepta %s como %d', (input, expected) => {
        expect(parse(input, 'es')).toBe(expected);
    });
    it.each([['1.234', 1234], ['12.345.678', 12345678], ['1.234,56', 1234.56]])(
        'sigue leyendo %s como miles es-ES (%d)', (input, expected) => {
            expect(parse(input, 'es')).toBe(expected);
        },
    );
    it.each(['0.123.456', '0.123,45'])('rechaza %s (miles con 0 delante)', (input) => {
        expect(parse(input, 'es')).toBeNull();
    });
});

describe.each([
    ['lib/i18n/parse-number', parseI18n],
    ['lib/format', parseFormat],
])('%s en-US: un 0 delante nunca es grupo de miles', (_name, parse) => {
    it('no lee «0,125» como 125', () => {
        expect(parse('0,125', 'en')).not.toBe(125);
    });
    it.each([['1,234', 1234], ['1,234.56', 1234.56], ['12,345,678', 12345678], ['0.125', 0.125], ['1234', 1234]])(
        'sigue leyendo %s como %d', (input, expected) => {
            expect(parse(input, 'en')).toBe(expected);
        },
    );
});
