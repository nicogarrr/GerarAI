import { describe, expect, it } from 'vitest';

import { isUsQuoteLine, quoteSymbolFor } from '@/lib/market/quote-symbol';

describe('quoteSymbolFor con ticker que ya lleva el sufijo de su plaza', () => {
    it.each([
        ['ITX.MC', 'BME', 'ITX.MC'],
        ['san.mc', 'BOLSA DE MADRID', 'SAN.MC'],
        ['SAP.DE', 'XETRA', 'SAP.DE'],
        ['ASML.AS', 'NYSE EURONEXT - EURONEXT AMSTERDAM', 'ASML.AS'],
        ['SHOP.TO', 'TORONTO STOCK EXCHANGE', 'SHOP.TO'],
        ['NESN.SW', 'SWISS EXCHANGE', 'NESN.SW'],
    ])('%s en %s cotiza como %s (no con el sufijo duplicado)', (ticker, exchange, expected) => {
        expect(quoteSymbolFor({ exchange, currency: 'EUR' }, ticker)).toBe(expected);
    });

    it('el ticker pelado sigue recibiendo su sufijo', () => {
        expect(quoteSymbolFor({ exchange: 'BME', currency: 'EUR' }, 'ITX')).toBe('ITX.MC');
        expect(quoteSymbolFor({ exchange: 'XETRA', currency: 'EUR' }, 'SAP')).toBe('SAP.DE');
    });

    it('un ticker con sufijo no-US no pasa a ser línea US', () => {
        expect(isUsQuoteLine({ exchange: 'BME', currency: 'EUR' }, 'ITX.MC')).toBe(false);
    });
});
