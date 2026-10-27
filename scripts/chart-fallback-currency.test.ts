/**
 * realqa-18: la ficha de CGEO.L pintaba «N/D | N/D» en la cabecera aunque el
 * gráfico mostraba el cierre (4.215 GBX). El fallback al último cierre del
 * gráfico estaba vetado para cualquier listado en subunidad.
 * Ejecución: node --experimental-strip-types --test scripts/chart-fallback-currency.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { chartFallbackCurrency, isSubunitListing, normalizeSubunitCurrency } from '../lib/market/chart-fallback-currency.ts';

void test('CGEO.L con el maestro en GBX: la cabecera puede usar el cierre del gráfico en GBX', () => {
    assert.equal(chartFallbackCurrency({ ticker: 'CGEO.L', symbol: 'CGEO.L', exchange: 'LSE', currency: 'GBX' }), 'GBX');
    assert.equal(chartFallbackCurrency({ ticker: 'CGEO.L', symbol: 'CGEO.L', exchange: 'LONDON STOCK EXCHANGE', currency: 'GBX' }), 'GBX');
});

void test('código de Yahoo GBp/ZAc se normaliza a GBX/ZAC', () => {
    assert.equal(normalizeSubunitCurrency('GBp'), 'GBX');
    assert.equal(normalizeSubunitCurrency('ZAc'), 'ZAC');
    assert.equal(chartFallbackCurrency({ ticker: 'CGEO.L', symbol: 'CGEO.L', exchange: 'LSE', currency: 'GBp' }), 'GBX');
    assert.equal(chartFallbackCurrency({ ticker: 'NPN.JO', symbol: 'NPN.JO', exchange: 'JOHANNESBURG', currency: 'ZAc' }), 'ZAC');
});

void test('listado en subunidad con la unidad grande declarada (GBP en un .L): sin fallback, escala ambigua x100', () => {
    assert.equal(chartFallbackCurrency({ ticker: 'CGEO.L', symbol: 'CGEO.L', exchange: 'LSE', currency: 'GBP' }), null);
    assert.equal(chartFallbackCurrency({ ticker: 'TEVA.TA', symbol: 'TEVA.TA', exchange: 'TEL AVIV', currency: 'ILS' }), null);
});

void test('listados normales: sin cambios (POOL en USD, KRKNF, divisa ausente o inválida)', () => {
    assert.equal(chartFallbackCurrency({ ticker: 'POOL', symbol: 'POOL', exchange: 'NASDAQ', currency: 'USD' }), 'USD');
    assert.equal(chartFallbackCurrency({ ticker: 'SAN.MC', symbol: 'SAN.MC', exchange: 'BME', currency: 'EUR' }), 'EUR');
    assert.equal(chartFallbackCurrency({ ticker: 'POOL', symbol: 'POOL', exchange: 'NASDAQ', currency: null }), null);
    assert.equal(chartFallbackCurrency({ ticker: 'POOL', symbol: 'POOL', exchange: 'NASDAQ', currency: 'us dollar' }), null);
});

void test('detección de subunidad por sufijo, bolsa o divisa', () => {
    assert.equal(isSubunitListing({ ticker: 'CGEO.L' }), true);
    assert.equal(isSubunitListing({ ticker: 'CGEO', exchange: 'LSE' }), true);
    assert.equal(isSubunitListing({ ticker: 'X', currency: 'GBp' }), true);
    assert.equal(isSubunitListing({ ticker: 'POOL', exchange: 'NASDAQ', currency: 'USD' }), false);
});
