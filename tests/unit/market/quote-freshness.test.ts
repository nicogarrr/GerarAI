// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { classifyQuoteKind, mapBackendYahooQuote, sanitizeFinnhubQuote, sessionDateEt } from '@/lib/market/quote-freshness';
import { isUsQuoteLine, quoteSymbolFor } from '@/lib/market/quote-symbol';

const utc = (d: number, h: number, mi = 0, mo = 9) => Date.UTC(2026, mo, d, h, mi);
const sec = (ms: number) => ms / 1000;

describe('classifyQuoteKind (EDT: 13:30-20:00 UTC)', () => {
    const now = utc(28, 16, 0); // miércoles 12:00 ET, sesión abierta
    it('sesión abierta: solo lo de esta sesión es live', () => {
        expect(classifyQuoteKind(sec(utc(28, 15, 59)), now)).toBe('live');
        expect(classifyQuoteKind(sec(utc(28, 13, 30)), now)).toBe('live'); // justo a la apertura
        expect(classifyQuoteKind(sec(utc(28, 13, 29)), now)).toBe('stale'); // un minuto antes de abrir
        expect(classifyQuoteKind(sec(utc(27, 19, 59)), now)).toBe('stale'); // caché de ayer servida hoy
    });
    it('tras el cierre: el dato de hoy es un cierre, el de ayer es stale', () => {
        const after = utc(28, 21, 0);
        expect(classifyQuoteKind(sec(utc(28, 19, 59)), after)).toBe('close');
        expect(classifyQuoteKind(sec(utc(27, 19, 59)), after)).toBe('stale');
    });
    it('premercado de martes: vale el cierre de ayer, no el de anteayer', () => {
        const pre = utc(27, 12, 0); // martes 08:00 ET
        expect(classifyQuoteKind(sec(utc(26, 19, 59)), pre)).toBe('close');
        expect(classifyQuoteKind(sec(utc(25, 19, 59)), pre)).toBe('stale');
    });
    it('lunes y fin de semana: la referencia es el viernes', () => {
        const mondayPre = utc(26, 12, 0);
        const saturday = utc(24, 15, 0);
        const sunday = utc(25, 15, 0);
        const friday = sec(utc(23, 19, 59));
        const thursday = sec(utc(22, 19, 59));
        for (const now of [mondayPre, saturday, sunday]) {
            expect(classifyQuoteKind(friday, now)).toBe('close');
            expect(classifyQuoteKind(thursday, now)).toBe('stale');
        }
    });
    it('timestamps rotos: cero, negativo, NaN o futuro (>15 min) son stale', () => {
        expect(classifyQuoteKind(0, now)).toBe('stale');
        expect(classifyQuoteKind(-5, now)).toBe('stale');
        expect(classifyQuoteKind(Number.NaN, now)).toBe('stale');
        expect(classifyQuoteKind(sec(now + 16 * 60_000), now)).toBe('stale');
        expect(classifyQuoteKind(sec(now + 10 * 60_000), now)).toBe('live'); // margen de reloj
    });
});

describe('sesión ET', () => {
    it('sessionDateEt usa el día de Nueva York, no el UTC', () => {
        expect(sessionDateEt(sec(Date.UTC(2026, 9, 28, 2, 0)))).toBe('2026-10-27'); // 22:00 ET del 27
        expect(sessionDateEt(sec(Date.UTC(2026, 9, 28, 15, 0)))).toBe('2026-10-28');
    });
});

describe('sanitizeFinnhubQuote / mapBackendYahooQuote', () => {
    const now = utc(28, 16, 0);
    it('acepta un quote fresco y conserva los campos; rechaza stale y vacíos', () => {
        const ok = sanitizeFinnhubQuote({ c: 10, d: 1, dp: 2, h: 11, l: 9, o: 9.5, pc: 9, t: sec(utc(28, 15, 0)) }, now);
        expect(ok).toMatchObject({ source: 'Finnhub', c: 10, pc: 9, kind: 'live' });
        expect(sanitizeFinnhubQuote({ c: 10, pc: 9, t: sec(utc(20, 15, 0)) }, now)).toBeNull(); // cache vieja 429
        expect(sanitizeFinnhubQuote({ c: 0, pc: 0, t: sec(now) }, now)).toBeNull();
        expect(sanitizeFinnhubQuote(null, now)).toBeNull();
        expect(sanitizeFinnhubQuote({ c: 10, pc: 9 }, now)).toBeNull(); // sin t no hay frescura demostrable
    });
    it('Yahoo del backend: sin hora, solo con la fecha exacta de la vela; fecha imposible => null', () => {
        const q = mapBackendYahooQuote({ c: 5, d: 'x' as unknown as number, dp: Number.NaN, pc: 4, cd: '2026-10-27' });
        expect(q).toMatchObject({ source: 'Yahoo Finance', t: null, kind: 'close', closeDate: '2026-10-27', d: null, dp: null }); // sin cambio valido: null, no 0,00 %
        expect(mapBackendYahooQuote({ c: 5, d: 1, dp: 25, pc: 4 })).toMatchObject({ d: 1, dp: 25 });

        expect(mapBackendYahooQuote({ c: 5, cd: '2026-02-31' })!.closeDate).toBeNull(); // no acepta desbordes de calendario
        expect(mapBackendYahooQuote({ c: 5, cd: 'ayer' })!.closeDate).toBeNull();
        expect(mapBackendYahooQuote({ c: 0, pc: 0 })).toBeNull();
        expect(mapBackendYahooQuote(undefined)).toBeNull();
    });
});

describe('quoteSymbolFor: nunca el ticker desnudo de otro emisor', () => {
    it('listados US por bolsa o divisa devuelven el ticker', () => {
        expect(quoteSymbolFor({ exchange: 'NASDAQ NMS', currency: 'USD' }, 'ASTS')).toBe('ASTS');
        expect(quoteSymbolFor({ exchange: 'UNKNOWN', currency: 'USD' }, 'BN')).toBe('BN');
        expect(quoteSymbolFor({ exchange: '', currency: 'USD' }, 'X')).toBe('X');
        expect(quoteSymbolFor({ exchange: 'NYSE', currency: '' }, 'KO')).toBe('KO'); // sin divisa vale la bolsa US
    });
    it('plazas no-US usan el sufijo verificado', () => {
        expect(quoteSymbolFor({ exchange: 'BME', currency: 'EUR' }, 'SAN')).toBe('SAN.MC');
        expect(quoteSymbolFor({ exchange: 'XETRA', currency: 'EUR' }, 'SAP')).toBe('SAP.DE');
        expect(quoteSymbolFor({ exchange: 'NYSE EURONEXT - EURONEXT AMSTERDAM', currency: '' }, 'ASML')).toBe('ASML.AS');
    });
    it('Euronext sin mapa y no-US sin correspondencia: null (ni gemelo US ni sufijo inventado)', () => {
        expect(quoteSymbolFor({ exchange: 'EURONEXT PARIS', currency: '' }, 'MC')).toBeNull();
        expect(quoteSymbolFor({ exchange: 'BOLSA X', currency: 'EUR' }, 'ALM')).toBeNull();
        expect(quoteSymbolFor({ exchange: 'NASDAQ', currency: 'EUR' }, 'ALM')).toBeNull();
        expect(quoteSymbolFor(null, 'AAPL')).toBeNull();
        expect(quoteSymbolFor(undefined, 'AAPL')).toBeNull();
    });
    it('Londres: solo si el ticker ya es el símbolo .L', () => {
        expect(quoteSymbolFor({ exchange: 'LONDON STOCK EXCHANGE', currency: 'GBP' }, 'cgeo.l')).toBe('CGEO.L');
        expect(quoteSymbolFor({ exchange: 'LSE', currency: 'GBP' }, 'AZN')).toBeNull();
    });
    it('isUsQuoteLine distingue la línea US de .L y de sufijos', () => {
        expect(isUsQuoteLine({ exchange: 'NASDAQ', currency: 'USD' }, 'ASTS')).toBe(true);
        expect(isUsQuoteLine({ exchange: 'LSE', currency: 'GBP' }, 'CGEO.L')).toBe(false);
        expect(isUsQuoteLine({ exchange: 'BME', currency: 'EUR' }, 'SAN')).toBe(false);
        expect(isUsQuoteLine({ exchange: 'BOLSA X', currency: 'EUR' }, 'ALM')).toBe(false);
        expect(isUsQuoteLine(null, 'ALM')).toBe(false);
    });
});
