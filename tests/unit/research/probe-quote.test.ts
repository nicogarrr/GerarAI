import { describe, expect, it } from 'vitest';

import { probeQuoteFromBackend } from '@/lib/market/probe-quote';

describe('probeQuoteFromBackend', () => {
    it('mapea precio y divisa de la misma fuente', () => {
        expect(probeQuoteFromBackend({ c: 102.5, pc: 100, currency: 'EUR' })).toEqual({
            price: 102.5,
            currency: 'EUR',
        });
    });

    it('normaliza unidades menores como la watchlist (GBp -> GBP)', () => {
        expect(probeQuoteFromBackend({ c: 118.25, pc: 117, currency: 'GBp' })).toEqual({
            price: 1.1825,
            currency: 'GBP',
        });
    });

    it('sin precio valido devuelve null (fallback por candidata)', () => {
        expect(probeQuoteFromBackend({ c: 0, pc: 0, currency: 'USD' })).toBeNull();
        expect(probeQuoteFromBackend(null)).toBeNull();
        expect(probeQuoteFromBackend(undefined)).toBeNull();
    });

    it('sin divisa declarada devuelve null: precio y divisa nunca se mezclan de fuentes distintas', () => {
        expect(probeQuoteFromBackend({ c: 250.1, pc: 248 })).toBeNull();
    });
});
