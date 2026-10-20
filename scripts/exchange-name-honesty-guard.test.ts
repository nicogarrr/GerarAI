/**
 * Guarda F156: la UI nunca muestra la subdivisión de mercado del proveedor
 * («NASDAQ NMS - GLOBAL MARKET») como si fuera verificable - PARA figura en
 * Nasdaq Capital Market según su 8-K. Se muestra solo el mercado normalizado.
 * Test semántico del helper + uso en las dos superficies.
 *
 * Ejecución: node --experimental-strip-types --test scripts/exchange-name-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
    exchangeDisplayName,
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
} from '../lib/exchangeName.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const readSource = (rel: string) => readFileSync(join(root, rel), 'utf8');

describe('exchangeDisplayName (semántica F156)', () => {
    it('la subdivisión no verificable desaparece: solo el mercado', () => {
        assert.equal(exchangeDisplayName('NASDAQ NMS - GLOBAL MARKET'), 'NASDAQ');
        assert.equal(exchangeDisplayName('NASDAQ NMS - GLOBAL SELECT MARKET'), 'NASDAQ');
        assert.equal(exchangeDisplayName('NEW YORK STOCK EXCHANGE, INC.'), 'NYSE');
        assert.equal(exchangeDisplayName('NYSE MKT LLC'), 'NYSE American');
    });

    it('«NYSE EURONEXT - ...» es una plaza Euronext, nunca NYSE (F180)', () => {
        // Finnhub nombra las plazas Euronext con su nomenclatura histórica;
        // mostrar «NYSE» para ASML (Amsterdam, EUR) rompía el par bolsa/divisa.
        assert.equal(exchangeDisplayName('NYSE EURONEXT - EURONEXT AMSTERDAM'), 'Euronext Amsterdam');
        assert.equal(exchangeDisplayName('NYSE EURONEXT - EURONEXT PARIS'), 'Euronext Paris');
        assert.notEqual(exchangeDisplayName('NYSE EURONEXT - EURONEXT AMSTERDAM'), 'NYSE');
    });

    it('mercados internacionales y OTC se normalizan sin inventar', () => {
        assert.equal(exchangeDisplayName('BOLSA DE MADRID'), 'BME');
        assert.equal(exchangeDisplayName('TORONTO STOCK EXCHANGE'), 'TSX');
        assert.equal(exchangeDisplayName('OTC MARKETS'), 'OTC');
        assert.equal(exchangeDisplayName('SWISS EXCHANGE'), 'SIX');
    });

    it('desconocido o vacío no se muestra (null), nunca «UNKNOWN»', () => {
        assert.equal(exchangeDisplayName('UNKNOWN'), null);
        assert.equal(exchangeDisplayName('UNKNOWN_EXCHANGE'), null);
        assert.equal(exchangeDisplayName(''), null);
        assert.equal(exchangeDisplayName(null), null);
        assert.equal(exchangeDisplayName(undefined), null);
    });
});

describe('superficies (F156)', () => {
    it('ficha y panel de mercado usan el nombre normalizado', () => {
        const page = readSource('app/(root)/research/[ticker]/page.tsx');
        assert.ok(page.includes('exchangeDisplayName(company.exchange)'), 'la ficha normaliza el exchange');
        assert.ok(!page.includes('<Badge variant="outline">{company.exchange}</Badge>'), 'exchange crudo vetado en la ficha');
    });
});
