/**
 * Tests semánticos del símbolo de cotización (F159/F160): el símbolo alimenta
 * quote Y candles (mismo `quoteSymbol` en getCompanyMarketSnapshot), así que
 * cada escenario cubre ambas vías. Regla: sin identidad de listado verificada
 * o sin correspondencia de bolsa validada, null = «cotización no disponible»;
 * nunca el ticker desnudo, que puede cotizar a otro emisor.
 * Ejecución: node --experimental-strip-types --test scripts/quote-symbol-semantics.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { quoteSymbolFor } from '../lib/market/quote-symbol.ts';

void test('master inaccesible: sin precio, nunca ticker desnudo', () => {
    // Un 404/timeout del master no puede abrir fallback financiero a otro
    // emisor: ALM pelado en Finnhub es Almonty, no Almirall.
    assert.equal(quoteSymbolFor(null, 'ALM'), null);
    assert.equal(quoteSymbolFor(undefined, 'ASML'), null);
});

void test('listado no-US con correspondencia validada: Yahoo con sufijo', () => {
    assert.equal(quoteSymbolFor({ exchange: 'BME', currency: 'EUR' }, 'ALM'), 'ALM.MC');
    assert.equal(
        quoteSymbolFor({ exchange: 'NYSE EURONEXT - EURONEXT AMSTERDAM', currency: 'EUR' }, 'ASML'),
        'ASML.AS',
    );
    assert.equal(quoteSymbolFor({ exchange: 'TORONTO STOCK EXCHANGE', currency: 'CAD' }, 'BHC'), 'BHC.TO');
    assert.equal(quoteSymbolFor({ exchange: 'SWISS EXCHANGE', currency: 'CHF' }, 'UHR'), 'UHR.SW');
});

void test('listado no-US sin correspondencia validada: sin precio', () => {
    // Londres/París/Italia no mapeadas: ni ticker desnudo ni sufijo adivinado.
    assert.equal(quoteSymbolFor({ exchange: 'LONDON STOCK EXCHANGE', currency: 'GBP' }, 'AZN'), null);
    // EUR de bolsa no reconocida: .MC podría cotizar un homónimo español.
    assert.equal(quoteSymbolFor({ exchange: 'UNKNOWN', currency: 'EUR' }, 'XYZ'), null);
    assert.equal(quoteSymbolFor({ exchange: 'EURONEXT PARIS', currency: 'EUR' }, 'MC'), null);
    // CAD en bolsa no mapeada.
    assert.equal(quoteSymbolFor({ exchange: 'TSX VENTURE EXCHANGE', currency: 'CAD' }, 'ABC'), null);
    // F165: NVO Copenhague/DKK - el ADR NYSE en USD no es la línea DKK.
    assert.equal(quoteSymbolFor({ exchange: 'OMX NORDIC EXCHANGE COPENHAGEN', currency: 'DKK' }, 'NVO'), null);
    // F166: SHEL LSE/USD - la divisa «cuadra» pero la bolsa declara Londres:
    // la línea US del ticker pelado no es el instrumento británico.
    assert.equal(quoteSymbolFor({ exchange: 'LONDON STOCK EXCHANGE', currency: 'USD' }, 'SHEL'), null);
});

void test('bolsa histórica Euronext con divisa ausente: línea real, nunca el ADR', () => {
    // «NYSE EURONEXT - ...» contiene «NYSE» y la divisa ausente es un estado
    // permitido: la inferencia US devolvía el ticker pelado (ADR en USD).
    assert.equal(
        quoteSymbolFor({ exchange: 'NYSE EURONEXT - EURONEXT AMSTERDAM', currency: '' }, 'ASML'),
        'ASML.AS',
    );
    assert.equal(
        quoteSymbolFor({ exchange: 'NYSE EURONEXT - EURONEXT AMSTERDAM' }, 'ASML'),
        'ASML.AS',
    );
    // Plaza Euronext no mapeada y sin divisa: ninguna plaza Euronext es US:
    // sin precio antes que el ticker pelado.
    assert.equal(quoteSymbolFor({ exchange: 'NYSE EURONEXT - EURONEXT PARIS', currency: '' }, 'MC'), null);
    assert.equal(quoteSymbolFor({ exchange: 'EURONEXT', currency: '' }, 'MC'), null);
});

void test('listado US: ticker pelado', () => {
    assert.equal(quoteSymbolFor({ exchange: 'NASDAQ NMS - GLOBAL MARKET', currency: 'USD' }, 'AAPL'), 'AAPL');
    assert.equal(quoteSymbolFor({ exchange: 'NEW YORK STOCK EXCHANGE, INC.', currency: 'USD' }, 'JNJ'), 'JNJ');
    // Bulk import americano: bolsa UNKNOWN pero divisa USD.
    assert.equal(quoteSymbolFor({ exchange: 'UNKNOWN', currency: 'USD' }, 'ACME'), 'ACME');
    assert.equal(quoteSymbolFor({ exchange: '', currency: 'USD' }, 'ACME'), 'ACME');
    assert.equal(quoteSymbolFor({ exchange: 'OTC MARKETS', currency: 'USD' }, 'ACME'), 'ACME');
});

void test('listado US con divisa de proveedor discordante (BABA): símbolo US, la divisa visible la pone el master', () => {
    // F163: Finnhub profile2 de BABA declara CNY aunque el listado NYSE
    // cotiza en USD; la tarjeta mostraba «109,74 CNY» con números del ADR
    // en USD. El símbolo es el pelado (listado US) y la composición
    // (guard quote-listing-match) garantiza researchCompany.currency primero.
    assert.equal(quoteSymbolFor({ exchange: 'NYSE', currency: 'USD' }, 'BABA'), 'BABA');
});

void test('F167: SAP XETRA cotiza en su listado real (.DE), no el ADS NYSE', () => {
    // XETRA -> .DE verificado contra Yahoo (SAP.DE: GER, EUR ~186; el ADS
    // NYSE:SAP son ~211 USD). Sin el mapa, la tarjeta mostraba «210,68 €».
    assert.equal(quoteSymbolFor({ exchange: 'XETRA', currency: 'EUR' }, 'SAP'), 'SAP.DE');
});

void test('TSM en bolsa de Taiwán: sin precio antes que el ADR en USD con etiqueta TWD', () => {
    // F164: la tarjeta mostraba «TAIWAN STOCK EXCHANGE · TWD» con los cinco
    // números del ADR NYSE:TSM en USD. Taiwán no está mapeada (y no puede
    // estarlo por sufijo: allí TSMC es 2330.TW, no TSM.TW), así que la
    // respuesta honesta es «cotización no disponible».
    assert.equal(quoteSymbolFor({ exchange: 'TAIWAN STOCK EXCHANGE', currency: 'TWD' }, 'TSM'), null);
});

void test('sin evidencia de listado (fila vacía): sin precio', () => {
    assert.equal(quoteSymbolFor({ exchange: '', currency: '' }, 'ACME'), null);
    assert.equal(quoteSymbolFor({}, 'ACME'), null);
});

void test('Londres: solo el simbolo de listado explicito (CGEO.L) cotiza; el pelado no', () => {
    assert.equal(quoteSymbolFor({ exchange: 'LSE', currency: 'GBX' }, 'CGEO.L'), 'CGEO.L');
    assert.equal(quoteSymbolFor({ exchange: 'LONDON STOCK EXCHANGE', currency: 'GBX' }, 'CGEO.L'), 'CGEO.L');
    assert.equal(quoteSymbolFor({ exchange: 'LSE', currency: 'GBX' }, 'CGEO'), null);
    assert.equal(quoteSymbolFor({ exchange: 'LONDON STOCK EXCHANGE', currency: 'USD' }, 'SHEL'), null);
});
