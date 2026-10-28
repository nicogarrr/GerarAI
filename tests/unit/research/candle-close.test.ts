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
        // Cierre oficial BME 17:30 Madrid (CET) = 16:30Z; margen 15 min -> 16:45Z.
        expect(isClosedCandle('2026-10-27', { symbol: 'SAN.MC', currency: 'EUR', now: at('2026-10-27T16:40:00Z') })).toBe(false);
        expect(isClosedCandle('2026-10-27', { symbol: 'SAN.MC', currency: 'EUR', now: at('2026-10-27T16:50:00Z') })).toBe(true);
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

describe('isClosedCandle: horarios oficiales y horario de verano por huso IANA', () => {
    const closed = (symbol: string, currency: string, day: string, nowIso: string) =>
        isClosedCandle(day, { symbol, currency, now: at(nowIso) });

    it('LSE 16:30 Londres: en invierno (GMT) 16:45Z, en verano (BST) 15:45Z', () => {
        expect(closed('CGEO.L', 'GBp', '2026-10-27', '2026-10-27T16:40:00Z')).toBe(false);
        expect(closed('CGEO.L', 'GBp', '2026-10-27', '2026-10-27T16:46:00Z')).toBe(true);
        expect(closed('CGEO.L', 'GBp', '2026-07-15', '2026-07-15T15:40:00Z')).toBe(false);
        expect(closed('CGEO.L', 'GBp', '2026-07-15', '2026-07-15T15:46:00Z')).toBe(true);
    });

    it('BME 17:30 Madrid: en verano (CEST) cierre a las 15:45Z', () => {
        expect(closed('SAN.MC', 'EUR', '2026-07-15', '2026-07-15T15:40:00Z')).toBe(false);
        expect(closed('SAN.MC', 'EUR', '2026-07-15', '2026-07-15T15:46:00Z')).toBe(true);
    });

    it('Euronext, Xetra y Milán cierran a las 17:30 CET', () => {
        for (const symbol of ['MC.PA', 'ASML.AS', 'ABI.BR', 'SAP.DE', 'ENI.MI']) {
            expect(closed(symbol, 'EUR', '2026-10-27', '2026-10-27T16:40:00Z')).toBe(false);
            expect(closed(symbol, 'EUR', '2026-10-27', '2026-10-27T16:46:00Z')).toBe(true);
        }
    });

    it('Euronext Lisboa cierra a las 16:30 de Lisboa (17:30 CET)', () => {
        expect(closed('EDP.LS', 'EUR', '2026-10-27', '2026-10-27T16:40:00Z')).toBe(false);
        expect(closed('EDP.LS', 'EUR', '2026-10-27', '2026-10-27T16:46:00Z')).toBe(true);
    });

    it('.F es el parqué de Fráncfort (22:00), no Xetra: a las 19:00 de Berlín aún puede ser parcial', () => {
        expect(closed('SAP.F', 'EUR', '2026-10-27', '2026-10-27T18:00:00Z')).toBe(false);
        expect(closed('SAP.F', 'EUR', '2026-10-27', '2026-10-27T21:16:00Z')).toBe(true);
    });

    it('SIX 17:30 Zúrich', () => {
        expect(closed('NESN.SW', 'CHF', '2026-10-27', '2026-10-27T16:40:00Z')).toBe(false);
        expect(closed('NESN.SW', 'CHF', '2026-10-27', '2026-10-27T16:46:00Z')).toBe(true);
    });

    it('TSX 16:00 Toronto, con su propio horario de verano', () => {
        // 27/10: Toronto en EDT (UTC-4) -> 20:15Z.
        expect(closed('SHOP.TO', 'CAD', '2026-10-27', '2026-10-27T20:10:00Z')).toBe(false);
        expect(closed('SHOP.TO', 'CAD', '2026-10-27', '2026-10-27T20:16:00Z')).toBe(true);
        // 15/12: EST (UTC-5) -> 21:15Z.
        expect(closed('SHOP.TO', 'CAD', '2026-12-15', '2026-12-15T21:10:00Z')).toBe(false);
        expect(closed('SHOP.TO', 'CAD', '2026-12-15', '2026-12-15T21:16:00Z')).toBe(true);
    });

    it('semanas en que EE. UU. y Europa no coinciden en el cambio de hora (marzo)', () => {
        // 10/03/2026: Nueva York ya en EDT (UTC-4), Madrid aún en CET (UTC+1).
        expect(closed('AAPL', 'USD', '2026-03-10', '2026-03-10T20:10:00Z')).toBe(false);
        expect(closed('AAPL', 'USD', '2026-03-10', '2026-03-10T20:16:00Z')).toBe(true);
        expect(closed('SAN.MC', 'EUR', '2026-03-10', '2026-03-10T16:40:00Z')).toBe(false);
        expect(closed('SAN.MC', 'EUR', '2026-03-10', '2026-03-10T16:46:00Z')).toBe(true);
    });

    it('EE. UU. en invierno (EST): cierre a las 21:15Z', () => {
        expect(closed('AAPL', 'USD', '2026-12-15', '2026-12-15T21:10:00Z')).toBe(false);
        expect(closed('AAPL', 'USD', '2026-12-15', '2026-12-15T21:16:00Z')).toBe(true);
    });
});
