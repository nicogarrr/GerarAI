/**
 * Tests del fix focal /mercados (21-oct-2026):
 *  - decimales por instrumento: cruces FX sin JPY a 4, con JPY a 3, y el
 *    cambio nunca se pinta como "+0,00"/"-0,00" siendo distinto de cero;
 *  - pre/post mercado: el parse elige el precio mas reciente segun las horas
 *    del proveedor (fixture con timestamp PASADO: no hace falta mercado
 *    abierto para verificarlo) y lo etiqueta con su sesion;
 *  - antigüedad calculada por fila (quoteAgeSeconds/formatQuoteAge);
 *  - identidad del instrumento desde el meta del proveedor (exchangeName/
 *    instrumentType), nunca derivada de la etiqueta visible.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { LIVE_FX, LIVE_QUOTE_GROUPS, formatQuoteAge, formatQuoteChange, localizeInstrumentType, parseYahooQuote, quoteAgeSeconds } from '../lib/market/live-quotes.ts';

test('catalogo: cada spec declara decimales enteros 2-5', () => {
    for (const group of LIVE_QUOTE_GROUPS) {
        for (const spec of group.specs) {
            assert.ok(Number.isInteger(spec.decimals) && spec.decimals >= 2 && spec.decimals <= 5,
                `${spec.symbol}: decimals=${spec.decimals}`);
        }
    }
});

test('catalogo FX: cruces sin JPY a 4 decimales, cruces con JPY a 3', () => {
    for (const spec of LIVE_FX) {
        const esperados = spec.symbol.includes('JPY') ? 3 : 4;
        assert.equal(spec.decimals, esperados, `${spec.symbol}: ${spec.decimals} != ${esperados}`);
    }
});

test('formato: el cambio FX real ya no redondea a "+0,00"', () => {
    // EUR/USD moviendose 14 pips: antes se pintaba "+0,00" (2 decimales).
    assert.equal(formatQuoteChange(0.0014, 4), '+0,0014');
    // Un cambio diminuto en un instrumento de 2 decimales no se pinta "-0,00".
    assert.equal(formatQuoteChange(-0.0041, 2), '-0,0041');
    // Cambio normal conserva los decimales del instrumento.
    assert.equal(formatQuoteChange(0.29, 2), '+0,29');
    // Cero exacto se pinta "+0,00" honestamente (sin ampliar).
    assert.equal(formatQuoteChange(0, 2), '+0,00');
});

test('parse premercado: precio pre mas reciente que el regular, con hora pasada del proveedor', () => {
    const spec = { symbol: 'ES=F', name: 'Futuro S&P 500 (E-mini)', kind: 'futuro' as const, unit: 'index' as const, decimals: 2 };
    const regularTime = 1_700_000_000; // cierre regular de ayer (pasado)
    const quote = parseYahooQuote(spec, {
        regularMarketPrice: 7700,
        regularMarketTime: regularTime,
        preMarketPrice: 7712.5,
        preMarketTime: regularTime + 8 * 3600, // 8 h despues: premercado de hoy
        exchangeTimezoneName: 'UTC',
    }, { timestamps: [regularTime], closes: [7690] });
    assert.ok(quote);
    assert.equal(quote.session, 'pre');
    assert.equal(quote.price, 7712.5);
    assert.equal(quote.timestamp, regularTime + 8 * 3600);
    assert.equal(quote.change, 22.5);
});

test('parse postmercado: post mas reciente que el regular', () => {
    const spec = { symbol: 'BBVA.MC', name: 'BBVA', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const regularTime = 1_700_000_000;
    const quote = parseYahooQuote(spec, {
        regularMarketPrice: 22.9,
        regularMarketTime: regularTime,
        postMarketPrice: 22.98,
        postMarketTime: regularTime + 3600,
    });
    assert.ok(quote);
    assert.equal(quote.session, 'post');
    assert.equal(quote.price, 22.98);
});

test('parse: en sesion regular el precio regular es el mas reciente', () => {
    const spec = { symbol: '^GSPC', name: 'S&P 500', kind: 'indice' as const, unit: 'index' as const, decimals: 2 };
    const preTime = 1_700_000_000;
    const quote = parseYahooQuote(spec, {
        regularMarketPrice: 7720,
        regularMarketTime: preTime + 7200,
        preMarketPrice: 7710,
        preMarketTime: preTime,
    });
    assert.ok(quote);
    assert.equal(quote.session, 'regular');
    assert.equal(quote.price, 7720);
});

test('parse: sin horas fiables gana la sesion regular; sin precios sigue siendo null', () => {
    const spec = { symbol: 'X', name: 'X', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const quote = parseYahooQuote(spec, { regularMarketPrice: 10, preMarketPrice: 11 });
    assert.ok(quote);
    assert.equal(quote.session, 'regular');
    assert.equal(parseYahooQuote(spec, { preMarketPrice: null, postMarketPrice: undefined }), null);
});

test('antigüedad: segundos reales desde la hora del proveedor, nunca negativa', () => {
    const ts = 1_700_000_000;
    assert.equal(quoteAgeSeconds((ts + 180) * 1000, ts), 180);
    assert.equal(quoteAgeSeconds((ts - 60) * 1000, ts), 0); // desfase de reloj => 0
    assert.equal(quoteAgeSeconds(0, null), null);
    assert.equal(formatQuoteAge(45), 'hace 45 s');
    assert.equal(formatQuoteAge(600), 'hace ~10 min');
    assert.equal(formatQuoteAge(7200), 'hace 2 h');
});

test('identidad: exchangeName e instrumentType vienen del meta; ausentes => null', () => {
    const spec = { symbol: 'ES=F', name: 'Futuro S&P 500 (E-mini)', kind: 'futuro' as const, unit: 'index' as const, decimals: 2 };
    const quote = parseYahooQuote(spec, {
        regularMarketPrice: 7700, regularMarketTime: 100,
        exchangeName: 'CME', instrumentType: 'FUTURE',
    });
    assert.ok(quote);
    assert.equal(quote.exchangeName, 'CME');
    assert.equal(quote.instrumentType, 'FUTURE');
    const sinMeta = parseYahooQuote(spec, { regularMarketPrice: 7700, regularMarketTime: 100 });
    assert.ok(sinMeta);
    assert.equal(sinMeta.exchangeName, null);
    assert.equal(sinMeta.instrumentType, null);
    assert.equal(localizeInstrumentType('FUTURE'), 'futuro');
    assert.equal(localizeInstrumentType('EQUITY'), 'acción');
    assert.equal(localizeInstrumentType('OTRA_COSA'), null);
    assert.equal(localizeInstrumentType(null), null);
});

/* ---- Cierre de referencia por dia/sesion con barras reales (auditor 21-oct) ----
   Caso real ^GSPC: el meta chartPreviousClose (7690,73) NO era el cierre del
   dia anterior (7712,57); con la referencia vieja el cambio salia +40,01 en
   vez de +18,17. La referencia ahora sale SOLO de las barras diarias. */

test('referencia: el meta con chartPreviousClose erroneo NO se usa; barras mandan', () => {
    const spec = { symbol: '^GSPC', name: 'S&P 500', kind: 'indice' as const, unit: 'index' as const, decimals: 2 };
    const bar1 = Date.UTC(2026, 9, 20, 13, 30) / 1000; // 20-oct 09:30 ET
    const bar2 = Date.UTC(2026, 9, 21, 13, 30) / 1000; // 21-oct 09:30 ET (barra de hoy, en formacion)
    const quoteTime = Date.UTC(2026, 9, 21, 20, 23) / 1000; // 21-oct 16:23 ET
    const meta = {
        regularMarketPrice: 7730.74,
        regularMarketTime: quoteTime,
        chartPreviousClose: 7690.73, // valor erroneo que traia el meta real
        exchangeTimezoneName: 'America/New_York',
    };
    const quote = parseYahooQuote(spec, meta, { timestamps: [bar1, bar2], closes: [7712.57, 7730.74] });
    assert.ok(quote);
    assert.ok(Math.abs((quote.change ?? 0) - 18.17) < 0.005, `change=${quote.change}`);
    assert.ok(Math.abs((quote.changePercent ?? 0) - 0.2356) < 0.01, `pct=${quote.changePercent}`);
});

test('referencia premercado: dia sin barra => cierre de la ultima barra existente', () => {
    const spec = { symbol: 'ES=F', name: 'Futuro S&P 500 (E-mini)', kind: 'futuro' as const, unit: 'index' as const, decimals: 2 };
    const bar1 = Date.UTC(2026, 9, 20, 13, 30) / 1000; // ultima sesion con barra
    const preTime = Date.UTC(2026, 9, 21, 11, 0) / 1000; // 21-oct 07:00 ET, premercado
    const quote = parseYahooQuote(spec, {
        preMarketPrice: 7720,
        preMarketTime: preTime,
        exchangeTimezoneName: 'America/New_York',
    }, { timestamps: [bar1], closes: [7712.57] });
    assert.ok(quote);
    assert.equal(quote.session, 'pre');
    assert.ok(Math.abs((quote.change ?? 0) - 7.43) < 0.005);
});

test('referencia fin de semana: cotizacion del sabado contra el cierre del viernes', () => {
    const spec = { symbol: 'EURUSD=X', name: 'EUR/USD', kind: 'divisa' as const, unit: 'cruz' as const, decimals: 4 };
    const friday = Date.UTC(2026, 9, 23, 13, 30) / 1000;
    const saturday = Date.UTC(2026, 9, 24, 14, 0) / 1000;
    const quote = parseYahooQuote(spec, {
        regularMarketPrice: 1.1234,
        regularMarketTime: saturday,
        exchangeTimezoneName: 'America/New_York',
    }, { timestamps: [friday], closes: [1.1200] });
    assert.ok(quote);
    assert.ok(Math.abs((quote.change ?? 0) - 0.0034) < 0.00001);
});

test('referencia: barra con close null se descarta; una sola barra del mismo dia => N/D', () => {
    const spec = { symbol: 'X', name: 'X', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const d1 = Date.UTC(2026, 9, 19, 7, 0) / 1000;
    const d2 = Date.UTC(2026, 9, 20, 7, 0) / 1000;
    // close null en la barra de hoy: solo queda la de ayer; cotizacion de hoy => referencia = ayer.
    const conNull = parseYahooQuote(spec, {
        regularMarketPrice: 105, regularMarketTime: d2 + 3600, exchangeTimezoneName: 'Europe/Madrid',
    }, { timestamps: [d1, d2], closes: [100, null] });
    assert.ok(conNull);
    assert.equal(conNull.change, 5);
    // Una sola barra del mismo dia: no hay sesion anterior demostrable => N/D.
    const unaBarra = parseYahooQuote(spec, {
        regularMarketPrice: 105, regularMarketTime: d2 + 3600, exchangeTimezoneName: 'Europe/Madrid',
    }, { timestamps: [d2], closes: [104] });
    assert.ok(unaBarra);
    assert.equal(unaBarra.change, null);
    assert.equal(unaBarra.changePercent, null);
});

test('referencia: sin zona horaria del mercado o sin hora de cotizacion => N/D', () => {
    const spec = { symbol: 'X', name: 'X', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const d1 = Date.UTC(2026, 9, 19, 7, 0) / 1000;
    const d2 = Date.UTC(2026, 9, 20, 7, 0) / 1000;
    const sinTz = parseYahooQuote(spec, { regularMarketPrice: 105, regularMarketTime: d2 }, { timestamps: [d1], closes: [100] });
    assert.ok(sinTz);
    assert.equal(sinTz.change, null);
    const sinHora = parseYahooQuote(spec, { regularMarketPrice: 105, exchangeTimezoneName: 'Europe/Madrid' }, { timestamps: [d1], closes: [100] });
    assert.ok(sinHora);
    assert.equal(sinHora.change, null);
});

test('referencia postmercado: contra el cierre regular de HOY probado por barra, nunca el de ayer', () => {
    const spec = { symbol: 'BBVA.MC', name: 'BBVA', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const ayer = Date.UTC(2026, 9, 20, 7, 0) / 1000;
    const hoy = Date.UTC(2026, 9, 21, 7, 0) / 1000;
    const postTime = Date.UTC(2026, 9, 21, 17, 30) / 1000; // hoy, tras el cierre regular
    const quote = parseYahooQuote(spec, {
        regularMarketPrice: 103,
        regularMarketTime: Date.UTC(2026, 9, 21, 15, 30) / 1000,
        postMarketPrice: 104,
        postMarketTime: postTime,
        exchangeTimezoneName: 'Europe/Madrid',
    }, { timestamps: [ayer, hoy], closes: [100, 103] });
    assert.ok(quote);
    assert.equal(quote.session, 'post');
    // 104 vs cierre regular de hoy (103) => +1; NO +4 contra ayer.
    assert.equal(quote.change, 1);
});

test('referencia postmercado sin barra de hoy => N/D, sin fallback al cierre de ayer', () => {
    const spec = { symbol: 'BBVA.MC', name: 'BBVA', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const ayer = Date.UTC(2026, 9, 20, 7, 0) / 1000;
    const postTime = Date.UTC(2026, 9, 21, 17, 30) / 1000;
    const quote = parseYahooQuote(spec, {
        postMarketPrice: 104,
        postMarketTime: postTime,
        exchangeTimezoneName: 'Europe/Madrid',
    }, { timestamps: [ayer], closes: [100] });
    assert.ok(quote);
    assert.equal(quote.session, 'post');
    assert.equal(quote.change, null);
    assert.equal(quote.changePercent, null);
});
