import { describe, expect, it } from 'vitest';
import { isClosedCandle, listingSession } from '@/lib/market/candle-close';

// 27/10/2026: Londres y Madrid ya en horario de invierno (UTC+0 / UTC+1); Nueva York aún en EDT (UTC-4).
const at = (iso: string) => new Date(iso);

describe('isClosedCandle', () => {
    it('CGEO.L: la vela de hoy es cierre tras el cierre de Londres aunque en Nueva York siga siendo el mismo día', () => {
        expect(isClosedCandle('2026-10-27', { symbol: 'CGEO.L', currency: 'GBp', now: at('2026-10-27T18:00:00Z') })).toBe(true);
    });

    it('CGEO.L: en plena sesión la vela de hoy puede ser parcial', () => {
        expect(isClosedCandle('2026-10-27', { symbol: 'CGEO.L', currency: 'GBp', now: at('2026-10-27T11:00:00Z') })).toBe(false);
    });

    it('SAN.MC: sigue parcial justo después del cierre (margen de subasta) y es cierre pasado el margen', () => {
        // Cierre BME 17:35 Madrid = 16:35Z; margen 15 min -> 16:50Z.
        expect(isClosedCandle('2026-10-27', { symbol: 'SAN.MC', currency: 'EUR', now: at('2026-10-27T16:40:00Z') })).toBe(false);
        expect(isClosedCandle('2026-10-27', { symbol: 'SAN.MC', currency: 'EUR', now: at('2026-10-27T16:55:00Z') })).toBe(true);
    });

    it('EE. UU.: cierre tras las 16:15 de Nueva York, parcial antes', () => {
        expect(isClosedCandle('2026-10-27', { symbol: 'AAPL', currency: 'USD', now: at('2026-10-27T19:00:00Z') })).toBe(false);
        expect(isClosedCandle('2026-10-27', { symbol: 'AAPL', currency: 'USD', now: at('2026-10-27T20:20:00Z') })).toBe(true);
    });

    it('BRK.B es clase de acción de EE. UU., no un sufijo de mercado', () => {
        expect(listingSession('BRK.B', 'USD')?.tz).toBe('America/New_York');
    });

    it('una vela de un día anterior siempre es cierre', () => {
        expect(isClosedCandle('2026-10-26', { symbol: 'SAN.MC', currency: 'EUR', now: at('2026-10-27T08:00:00Z') })).toBe(true);
    });

    it('mercado desconocido: conserva el criterio prudente (solo días anteriores en Nueva York)', () => {
        expect(listingSession('7203.T', 'JPY')).toBeNull();
        expect(isClosedCandle('2026-10-27', { symbol: '7203.T', currency: 'JPY', now: at('2026-10-27T23:00:00Z') })).toBe(false);
        expect(isClosedCandle('2026-10-26', { symbol: '7203.T', currency: 'JPY', now: at('2026-10-27T05:00:00Z') })).toBe(true);
    });

    it('acepta fechas con hora (ISO completo)', () => {
        expect(isClosedCandle('2026-10-27T00:00:00Z', { symbol: 'CGEO.L', currency: 'GBp', now: at('2026-10-27T18:00:00Z') })).toBe(true);
    });
});
