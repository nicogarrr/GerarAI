import { describe, expect, it } from 'vitest';
import { isUsQuoteLine, quoteSymbolFor } from '@/lib/market/quote-symbol';

const us = { exchange: 'NASDAQ', currency: 'USD' };

describe('quote-symbol: el ticker se normaliza a mayusculas', () => {
    it('linea US con ticker en minusculas o con espacios', () => {
        expect(quoteSymbolFor(us, 'aapl')).toBe('AAPL');
        expect(quoteSymbolFor(us, ' aapl ')).toBe('AAPL');
        expect(isUsQuoteLine(us, 'aapl')).toBe(true);
        expect(isUsQuoteLine(us, ' Aapl ')).toBe(true);
    });
    it('sufijos de plaza y Londres tambien salen en mayusculas', () => {
        expect(quoteSymbolFor({ exchange: 'BME', currency: 'EUR' }, 'itx')).toBe('ITX.MC');
        expect(quoteSymbolFor({ exchange: 'LONDON STOCK EXCHANGE', currency: 'GBP' }, 'cgeo.l')).toBe('CGEO.L');
    });
    it('las lineas no-US siguen sin ser US aunque el ticker venga en minusculas', () => {
        expect(isUsQuoteLine({ exchange: 'BME', currency: 'EUR' }, 'itx')).toBe(false);
        expect(isUsQuoteLine({ exchange: 'LSE', currency: 'GBP' }, 'cgeo.l')).toBe(false);
        expect(isUsQuoteLine({ exchange: 'XETRA', currency: 'EUR' }, 'sap')).toBe(false);
    });
    it('sin evidencia de plaza US: null, sin adivinar', () => {
        expect(quoteSymbolFor({ exchange: 'SIX', currency: 'CHF' }, 'nesn')).toBeNull();
        expect(isUsQuoteLine({ exchange: 'SIX', currency: 'CHF' }, 'nesn')).toBe(false);
    });
});
