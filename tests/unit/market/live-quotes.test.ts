// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
    formatQuoteAge, formatQuoteChange, formatQuoteChangePercent, localizeInstrumentType, parseYahooQuote,
    postReferenceCloseFromBars, quoteAgeSeconds, referenceCloseFromBars, yahooChartRequest,
    type LiveQuoteSpec,
} from '@/lib/market/live-quotes';

const SPEC: LiveQuoteSpec = { symbol: '^GSPC', name: 'S&P 500', kind: 'indice', unit: 'index', decimals: 2 };
const NY = 'America/New_York';
// 27-oct y 28-oct-2026 a las 21:00 UTC (17:00 ET): cierres de las barras diarias.
const D1 = Date.UTC(2026, 9, 27, 21, 0) / 1000;
const D2 = Date.UTC(2026, 9, 28, 21, 0) / 1000;
const bars = { timestamps: [D1, D2], closes: [7000, 7100] };

describe('referenceCloseFromBars', () => {
    it('cotización de un día CON barra: referencia = cierre de la barra anterior', () => {
        expect(referenceCloseFromBars(bars, D2 - 3600, NY)).toBe(7000);
    });
    it('una sola barra y cotización de ese día: sin referencia demostrable (null), no se inventa', () => {
        expect(referenceCloseFromBars({ timestamps: [D2], closes: [7100] }, D2 - 60, NY)).toBeNull();
    });
    it('cotización de un día SIN barra (premercado): referencia = último cierre existente', () => {
        const preMarket = Date.UTC(2026, 9, 29, 11, 0) / 1000; // 29-oct 07:00 ET
        expect(referenceCloseFromBars(bars, preMarket, NY)).toBe(7100);
    });
    it('descarta barras con cierre null/0/NaN y devuelve null sin datos válidos', () => {
        expect(referenceCloseFromBars({ timestamps: [D1, D2], closes: [null, 0] }, D2, NY)).toBeNull();
        expect(referenceCloseFromBars({ timestamps: [D1], closes: [Number.NaN] }, D1, NY)).toBeNull();
        expect(referenceCloseFromBars(null, D2, NY)).toBeNull();
    });
    it('sin hora de cotización, sin zona o con zona inválida: null', () => {
        expect(referenceCloseFromBars(bars, null, NY)).toBeNull();
        expect(referenceCloseFromBars(bars, D2, null)).toBeNull();
        expect(referenceCloseFromBars(bars, D2, 'No/Existe')).toBeNull();
    });
    it('usa el día del mercado, no el UTC: 23:30 ET del 27 sigue siendo día 27', () => {
        const lateEt = Date.UTC(2026, 9, 28, 3, 30) / 1000; // 27-oct 23:30 ET
        expect(referenceCloseFromBars({ timestamps: [D1], closes: [7000] }, lateEt, NY)).toBeNull(); // mismo día, una barra
    });
});

describe('postReferenceCloseFromBars', () => {
    it('postmercado: referencia = cierre regular de HOY', () => {
        expect(postReferenceCloseFromBars(bars, D2 + 1800, NY)).toBe(7100);
    });
    it('sin barra de hoy NUNCA cae al cierre de ayer', () => {
        const nextDay = Date.UTC(2026, 9, 29, 14, 0) / 1000;
        expect(postReferenceCloseFromBars(bars, nextDay, NY)).toBeNull();
    });
    it('entradas incompletas: null', () => {
        expect(postReferenceCloseFromBars(bars, null, NY)).toBeNull();
        expect(postReferenceCloseFromBars(bars, D2, null)).toBeNull();
        expect(postReferenceCloseFromBars({ timestamps: [], closes: [] }, D2, NY)).toBeNull();
        expect(postReferenceCloseFromBars(bars, D2, 'Mal/Zona')).toBeNull();
    });
});

describe('parseYahooQuote', () => {
    it('sin meta o sin precio utilizable: null (la UI pinta N/D, nunca 0)', () => {
        expect(parseYahooQuote(SPEC, null)).toBeNull();
        expect(parseYahooQuote(SPEC, undefined)).toBeNull();
        expect(parseYahooQuote(SPEC, { regularMarketPrice: 0 })).toBeNull();
        expect(parseYahooQuote(SPEC, { regularMarketPrice: Number.NaN, preMarketPrice: -1 })).toBeNull();
    });
    it('calcula cambio y % contra el cierre anterior de las barras', () => {
        const q = parseYahooQuote(SPEC, {
            regularMarketPrice: 7140, regularMarketTime: D2 - 600, exchangeTimezoneName: NY, currency: 'USD',
            exchangeName: ' SNP ', instrumentType: 'INDEX',
        }, bars);
        expect(q).toMatchObject({ price: 7140, session: 'regular', exchangeName: 'SNP', instrumentType: 'INDEX', currency: 'USD', symbol: '^GSPC' });
        expect(q!.change).toBeCloseTo(140, 6);
        expect(q!.changePercent).toBeCloseTo(2, 6);
    });
    it('sin barras: cambio y % son null aunque el meta traiga previousClose engañoso', () => {
        const q = parseYahooQuote(SPEC, { regularMarketPrice: 7140, regularMarketTime: D2, exchangeTimezoneName: NY, ...{ chartPreviousClose: 1 } } as never);
        expect(q!.change).toBeNull();
        expect(q!.changePercent).toBeNull();
    });
    it('elige la sesión con la hora más reciente; a igualdad gana la regular', () => {
        const meta = { regularMarketPrice: 100, regularMarketTime: 1000, postMarketPrice: 101, postMarketTime: 2000, preMarketPrice: 99, preMarketTime: 500 };
        expect(parseYahooQuote(SPEC, meta)).toMatchObject({ price: 101, session: 'post' });
        expect(parseYahooQuote(SPEC, { ...meta, postMarketTime: 1000 })).toMatchObject({ price: 100, session: 'regular' });
        expect(parseYahooQuote(SPEC, { regularMarketPrice: 100, preMarketPrice: 99, preMarketTime: 1 })).toMatchObject({ session: 'pre' });
    });
    it('postmercado usa como referencia el cierre regular de hoy, no el de ayer', () => {
        const q = parseYahooQuote(SPEC, {
            regularMarketPrice: 7100, regularMarketTime: D2, postMarketPrice: 7150, postMarketTime: D2 + 1800, exchangeTimezoneName: NY,
        }, bars);
        expect(q!.session).toBe('post');
        expect(q!.change).toBeCloseTo(50, 6);
    });
    it('exchangeName cae a fullExchangeName; tipo/divisa no string se omiten', () => {
        const q = parseYahooQuote(SPEC, { regularMarketPrice: 5, fullExchangeName: 'CME Globex', instrumentType: '  ', currency: null });
        expect(q).toMatchObject({ exchangeName: 'CME Globex', instrumentType: null, currency: null, timestamp: null });
    });
});

describe('formato y antigüedad', () => {
    it('quoteAgeSeconds: null sin timestamp y nunca negativa', () => {
        expect(quoteAgeSeconds(1_000_000, null)).toBeNull();
        expect(quoteAgeSeconds(1_000_000, 940)).toBe(60);
        expect(quoteAgeSeconds(1_000_000, 2_000)).toBe(0);
    });
    it('formatQuoteAge distingue exacto, aproximado y horas', () => {
        expect(formatQuoteAge(Number.NaN)).toBe('N/D');
        expect(formatQuoteAge(Infinity)).toBe('N/D');
        expect(formatQuoteAge(0)).toBe('hace 0 s');
        expect(formatQuoteAge(-5)).toBe('hace 0 s');
        expect(formatQuoteAge(40.9)).toBe('hace 40 s');
        expect(formatQuoteAge(180)).toBe('hace ~3 min');
        expect(formatQuoteAge(3599)).toBe('hace 1 h');
        expect(formatQuoteAge(3600)).toBe('hace 1 h');
        expect(formatQuoteAge(7140)).toBe('hace 1 h 59 min');
    });
    it('formatQuoteChange y % amplían decimales para no mostrar un falso "0,00"', () => {
        expect(formatQuoteChange(1.5, 2)).toBe('+1,50');
        expect(formatQuoteChange(-0.0004, 4)).toBe('-0,0004');
        expect(formatQuoteChange(-0.0001, 2)).toBe('-0,0001');
        expect(formatQuoteChange(0, 2)).toBe('+0,00');
        expect(formatQuoteChangePercent(-0.001)).toBe('-0,0010');
        expect(formatQuoteChangePercent(1.234)).toBe('+1,23');
    });
    it('localizeInstrumentType traduce los conocidos y devuelve null para el resto', () => {
        expect(localizeInstrumentType('FUTURE')).toBe('futuro');
        expect(localizeInstrumentType('EQUITY')).toBe('acción');
        expect(localizeInstrumentType('INDEX')).toBe('índice');
        expect(localizeInstrumentType('CURRENCY')).toBe('divisa');
        expect(localizeInstrumentType('ETF')).toBe('ETF');
        expect(localizeInstrumentType('CRYPTOCURRENCY')).toBeNull();
        expect(localizeInstrumentType(null)).toBeNull();
    });
    it('yahooChartRequest codifica el símbolo y manda UA de navegador', () => {
        const r = yahooChartRequest('^GSPC');
        expect(r.url).toBe('https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=2d&interval=1d');
        expect((r.init.headers as Record<string, string>)['User-Agent']).toContain('Mozilla/5.0');
    });
});
