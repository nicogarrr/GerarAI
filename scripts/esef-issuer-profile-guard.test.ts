/** QA 18: la ficha decide FMP/ESEF/SEC por el perfil del emisor, no solo
 *  por el sufijo del ticker (los europeos canonicos no lo llevan: AENA).
 * Ejecución: node --experimental-strip-types --test scripts/esef-issuer-profile-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('existe la decision por perfil (ticker + mercado declarado)', () => {
    assert.match(page, /function isEsefIssuerProfile\(ticker: string, exchange: string \| null \| undefined\)/);
    assert.match(page, /function fmpCovers\(ticker: string, exchange: string \| null \| undefined\)/);
});

test('los mercados ESEF se reconocen por nombre (Finnhub incluido)', () => {
    assert.match(page, /\/BME\|BOLSA DE MADRID\/i/);
    assert.match(page, /\/EURONEXT\/i/);
});

test('los tres puntos de la vista financiera usan el perfil', () => {
    assert.match(page, /\{fmpCovers\(ticker, company\.exchange\) \? \(/);
    assert.match(page, /\{isEsefIssuerProfile\(ticker, company\.exchange\) \? \(/);
    assert.match(page, /fmpCovers\(ticker, company\.exchange\)\s*\n\s*\? t\('research\.fichaRefreshFinancialsFmp'\)/);
});

test('un emisor español sin sufijo ya no ve FMP ni SEC', () => {
    assert.doesNotMatch(page, /\{!ticker\.includes\('\.'\) \? \(/);
});
