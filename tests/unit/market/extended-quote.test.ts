// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { extendedQuoteLabel, quoteDate, quoteSessionDate, quoteTime, type ExtendedQuote } from '@/lib/market/extended-quote';

// 28-oct-2026 14:30 UTC = 15:30 en Madrid (CET desde el 25-oct).
const TS = Date.UTC(2026, 9, 28, 14, 30) / 1000;
const base = { source: 'Finnhub', timestamp: TS, price: 10, status: 'ok', session: 'regular', price_session: 'regular' } as unknown as ExtendedQuote;
const q = (over: Record<string, unknown>) => ({ ...base, ...over }) as unknown as ExtendedQuote;

describe('extendedQuoteLabel', () => {
    it('N/D sin quote, fuente, hora, precio, estado no disponible o sesión cerrada', () => {
        expect(extendedQuoteLabel(null)).toBe('N/D');
        expect(extendedQuoteLabel(q({ source: null }))).toBe('N/D');
        expect(extendedQuoteLabel(q({ timestamp: null }))).toBe('N/D');
        expect(extendedQuoteLabel(q({ price: null }))).toBe('N/D');
        expect(extendedQuoteLabel(q({ status: 'unavailable' }))).toBe('N/D');
        expect(extendedQuoteLabel(q({ price_session: 'cerrado' }))).toBe('N/D');
        expect(extendedQuoteLabel(q({ price_session: null }))).toBe('N/D');
    });
    it('misma sesión: etiqueta de sesión con hora de Madrid', () => {
        expect(extendedQuoteLabel(base)).toContain('Mercado abierto · ');
        expect(extendedQuoteLabel(base)).toContain('15:30');
        expect(extendedQuoteLabel(q({ session: 'pre', price_session: 'pre' }))).toContain('Premercado · ');
        expect(extendedQuoteLabel(q({ session: 'post', price_session: 'post' }))).toContain('Post-cierre · ');
    });
    it('sesión distinta: dato fechado, nunca "en vivo"', () => {
        expect(extendedQuoteLabel(q({ session: 'cerrado', price_session: 'post' }))).toContain('Último post-cierre · ');
        expect(extendedQuoteLabel(q({ session: 'cerrado', price_session: 'pre' }))).toContain('Último premercado · ');
        expect(extendedQuoteLabel(q({ session: 'pre', price_session: 'regular', regular_close_timestamp: TS }))).toContain('Cierre · ');
        expect(extendedQuoteLabel(q({ session: 'pre', price_session: 'regular', regular_close_timestamp: TS - 1 }))).toContain('Último precio regular · ');
    });
    it('marca los datos retrasados', () => {
        expect(extendedQuoteLabel(q({ status: 'retrasado' }))).toMatch(/ · Retrasado$/);
    });
});

describe('helpers de fecha', () => {
    it('quoteTime y quoteDate: N/D sin timestamp, hora y día de Madrid si hay', () => {
        expect(quoteTime(null)).toBe('N/D');
        expect(quoteTime(undefined)).toBe('N/D');
        expect(quoteTime(TS)).toBe('15:30');
        expect(quoteDate(0)).toBe('N/D');
        expect(quoteDate(TS)).toMatch(/28 oct/);
    });
    it('quoteSessionDate solo acepta YYYY-MM-DD y no afirma hora', () => {
        expect(quoteSessionDate(null)).toBe('N/D');
        expect(quoteSessionDate('28/10/2026')).toBe('N/D');
        expect(quoteSessionDate('2026-10-27')).toMatch(/27 oct 2026/);
    });
});
