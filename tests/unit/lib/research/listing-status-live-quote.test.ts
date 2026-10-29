import { describe, expect, it } from 'vitest';
import { hasCurrentQuote, listingStatus } from '@/lib/research/listing-status';

// Ficha /research/AAPL: «Ticker sin cotización vigente (sin cierre conocido)»
// salía justo encima de «349,64 US$ · Mercado abierto».
const now = new Date('2026-10-29T15:00:00Z');
const ts = (iso: string) => Date.parse(iso) / 1000;

describe('aviso sin cotización vigente con cotización actual', () => {
    it('una cotización en vivo de hoy cuenta como actual', () => {
        expect(hasCurrentQuote({ price: 349.64, timestamp: ts('2026-10-29T14:55:00Z'), status: 'ok' }, now)).toBe(true);
    });
    it('sin precio, precio 0, sin hora, no disponible o de hace más de 30 días: no cuenta', () => {
        expect(hasCurrentQuote(null, now)).toBe(false);
        expect(hasCurrentQuote({ price: null, timestamp: ts('2026-10-29T14:55:00Z') }, now)).toBe(false);
        expect(hasCurrentQuote({ price: 0, timestamp: ts('2026-10-29T14:55:00Z') }, now)).toBe(false);
        expect(hasCurrentQuote({ price: 10, timestamp: null }, now)).toBe(false);
        expect(hasCurrentQuote({ price: 10, timestamp: ts('2026-10-29T14:55:00Z'), status: 'unavailable' }, now)).toBe(false);
        expect(hasCurrentQuote({ price: 10, timestamp: ts('2026-09-01T20:00:00Z') }, now)).toBe(false);
    });
    it('con cotización actual no hay aviso, aunque falte el cierre o el mercado', () => {
        expect(listingStatus(null, null, now, true)).toEqual({ stale: false });
        expect(listingStatus('UNKNOWN', '2026-08-01', now, true)).toEqual({ stale: false });
    });
    it('sin cotización actual el aviso sigue igual (reglas de frescura sin cambios)', () => {
        expect(listingStatus(null, null, now, false)).toEqual({ stale: true, message: 'Ticker sin cotización vigente (sin cierre conocido)' });
        expect(listingStatus(null, null, now)).toEqual({ stale: true, message: 'Ticker sin cotización vigente (sin cierre conocido)' });
    });
});
