import { describe, expect, it } from 'vitest';
import { perState } from '@/lib/research/per';

describe('perState en inglés', () => {
    it('motivos del PER en inglés; español por defecto', () => {
        expect(perState({ quoteSymbol: null, ticker: 'SAN', peTTM: undefined, providerAvailable: false }, 'en').note).toBe('No verified quote listing');
        expect(perState({ quoteSymbol: 'SAN', ticker: 'SAN', peTTM: undefined, providerAvailable: false, usLine: false }, 'en').note).toBe('Listed outside the US: no verifiable P/E');
        expect(perState({ quoteSymbol: 'MSFT', ticker: 'MSFT', peTTM: 31.2, providerAvailable: true }, 'en')).toEqual({ value: 31.2, note: 'Finnhub · trailing 12 months' });
        expect(perState({ quoteSymbol: 'MSFT', ticker: 'MSFT', peTTM: -3, providerAvailable: true }, 'en').note).toMatch(/negative earnings/);
        expect(perState({ quoteSymbol: 'MSFT', ticker: 'MSFT', peTTM: 31.2, providerAvailable: true }).note).toBe('Finnhub · últimos 12 meses');
    });
});
