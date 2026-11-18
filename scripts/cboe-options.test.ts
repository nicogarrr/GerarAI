/**
 * Guard de lib/market/cboe-options.ts: parseo OCC, saneado defensivo de la
 * delayed quotes API de CBOE y disciplina de la caché (dedupe, TTL,
 * saturación, backoff con Retry-After, reloj inyectable).
 *
 * Ejecución: node --experimental-strip-types --test scripts/cboe-options.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import {
    cboeContractKey,
    createCboeChainCache,
    parseOccSymbol,
    sanitizeCboeChain,
    type CboeChainAttempt,
} from '../lib/market/cboe-options.ts';

test('parseOccSymbol: OCC estándar y rechazos', () => {
    assert.deepEqual(parseOccSymbol('ASTS261120C00045000'), { underlying: 'ASTS', expiry: '2026-11-20', callPut: 'call', strike: 45 });
    assert.deepEqual(parseOccSymbol('A261218P00050000'), { underlying: 'A', expiry: '2026-12-18', callPut: 'put', strike: 50 });
    assert.deepEqual(parseOccSymbol('asts261120c00045500'), { underlying: 'ASTS', expiry: '2026-11-20', callPut: 'call', strike: 45.5 });
    // Raíz ajustada (dígito tras letras), mes/día imposibles, formato corto: null.
    assert.equal(parseOccSymbol('ASTS1261120C00045000'), null);
    assert.equal(parseOccSymbol('ASTS261320C00045000'), null);
    assert.equal(parseOccSymbol('ASTS261131C00045000'), null);
    assert.equal(parseOccSymbol('ASTS'), null);
    assert.equal(parseOccSymbol('ASTS261120C0004500'), null);
    assert.equal(parseOccSymbol(null), null);
    assert.equal(parseOccSymbol(42), null);
});

test('cboeContractKey es estable y agnóstica a mayúsculas y decimales de strike', () => {
    assert.equal(cboeContractKey('asts', '2026-11-20', 'call', 45), cboeContractKey('ASTS', '2026-11-20', 'call', 45.0));
    assert.notEqual(cboeContractKey('ASTS', '2026-11-20', 'call', 45), cboeContractKey('ASTS', '2026-11-20', 'put', 45));
});

const cboePayload = {
    data: {
        symbol: 'ASTS',
        options: [
            { option: 'ASTS261120C00045000', last_trade_price: 0.01, last_trade_time: '2026-11-17T15:47:43', bid: 0, ask: 0.01 },
            { option: 'ASTS261218C00050000', last_trade_price: 2.3, last_trade_time: '2026-11-18T14:05:00' },
            // Sin operación registrada: precio y hora a null -> N/D honesto, nunca bid/ask inventado.
            { option: 'ASTS261218C00100000', last_trade_price: null, last_trade_time: null, bid: 0.05, ask: 0.1 },
            // Filas corruptas: se descartan, no envenenan la cadena.
            { option: 'ASTS1X', last_trade_price: 5 },
            { option: 'ASTS261218C00060000', last_trade_price: 'abc', last_trade_time: 'ayer' },
            { option: 'ASTS261218C00070000', last_trade_price: -4, last_trade_time: '2026-11-18T10:00:00' },
        ],
    },
};

test('sanitizeCboeChain: mapa por contrato con saneado defensivo', () => {
    const chain = sanitizeCboeChain(cboePayload);
    assert.ok(chain);
    assert.deepEqual(chain.get(cboeContractKey('ASTS', '2026-11-20', 'call', 45)), { lastTradePrice: 0.01, lastTradeTime: '2026-11-17T15:47:43' });
    assert.deepEqual(chain.get(cboeContractKey('ASTS', '2026-12-18', 'call', 50)), { lastTradePrice: 2.3, lastTradeTime: '2026-11-18T14:05:00' });
    assert.deepEqual(chain.get(cboeContractKey('ASTS', '2026-12-18', 'call', 100)), { lastTradePrice: null, lastTradeTime: null });
    // 'abc' y -4 no son precio: quedan null (el valuador los deja N/D), nunca NaN ni negativos.
    assert.deepEqual(chain.get(cboeContractKey('ASTS', '2026-12-18', 'call', 60)), { lastTradePrice: null, lastTradeTime: null });
    assert.equal(chain.get(cboeContractKey('ASTS', '2026-12-18', 'call', 70))?.lastTradePrice, null);
    assert.equal(sanitizeCboeChain({}), null);
    assert.equal(sanitizeCboeChain(null), null);
    assert.equal(sanitizeCboeChain({ data: { options: 'no-array' } }), null);
});

const okAttempt = (payload: unknown): CboeChainAttempt => {
    const chain = sanitizeCboeChain(payload);
    return { chain, fetchFailed: !chain, retryAfterSeconds: null };
};

test('caché: dedupe concurrente, TTL y fetchedAt real', async () => {
    let clock = 1_000_000;
    const cache = createCboeChainCache({ now: () => clock, ttlMs: 60_000 });
    let fetches = 0;
    const fetcher = async () => {
        fetches += 1;
        await new Promise((r) => setTimeout(r, 5));
        return okAttempt(cboePayload);
    };
    const [a, b, c] = await Promise.all([cache.getChain('ASTS', fetcher), cache.getChain('asts ', fetcher), cache.getChain('ASTS', fetcher)]);
    assert.equal(fetches, 1, 'ráfaga concurrente del mismo subyacente = UN fetch');
    assert.equal(a.chain?.size, b.chain?.size);
    assert.equal(c.fetchedAt, a.fetchedAt);
    clock += 30_000;
    await cache.getChain('ASTS', fetcher);
    assert.equal(fetches, 1, 'dentro del TTL se sirve de caché');
    clock += 31_000;
    await cache.getChain('ASTS', fetcher);
    assert.equal(fetches, 2, 'vencido el TTL se revalida');
});

test('caché: fallo con Retry-After frena el reintento; vencida la ventana reintenta', async () => {
    let clock = 0;
    const cache = createCboeChainCache({ now: () => clock });
    let fetches = 0;
    const failing = async (): Promise<CboeChainAttempt> => {
        fetches += 1;
        return { chain: null, fetchFailed: true, retryAfterSeconds: 120 };
    };
    const first = await cache.getChain('ASTS', failing);
    assert.equal(first.fetchFailed, true);
    clock += 30_000;
    const second = await cache.getChain('ASTS', failing);
    assert.equal(fetches, 1, 'dentro del Retry-After NO se reintenta');
    assert.equal(second.fetchFailed, true);
    assert.ok((second.retryAfterSeconds ?? 0) > 0);
    clock += 91_000;
    await cache.getChain('ASTS', failing);
    assert.equal(fetches, 2, 'vencida la ventana se reintenta');
});

test('caché: saturación de concurrencia = degradado inmediato sin fetch ni bloqueo', async () => {
    const cache = createCboeChainCache({ maxInflight: 2 });
    let fetches = 0;
    const slow = async (): Promise<CboeChainAttempt> => {
        fetches += 1;
        await new Promise((r) => setTimeout(r, 20));
        return okAttempt(cboePayload);
    };
    const p1 = cache.getChain('AAA', slow);
    const p2 = cache.getChain('BBB', slow);
    const third = await cache.getChain('CCC', slow);
    assert.equal(third.saturated, true);
    assert.equal(third.chain, null);
    assert.equal(fetches, 2, 'el saturado no abrió un tercer fetch');
    await Promise.all([p1, p2]);
});

test('caché: timeout del fetch cuenta como fallo y no envenena con dato tardío', async () => {
    const cache = createCboeChainCache({ fetchTimeoutMs: 10, failureBackoffBaseMs: 1, failureBackoffCapMs: 1 });
    const zombie = async (): Promise<CboeChainAttempt> => {
        await new Promise((r) => setTimeout(r, 100));
        return okAttempt(cboePayload);
    };
    const r = await cache.getChain('ASTS', zombie);
    assert.equal(r.chain, null);
    assert.equal(r.fetchFailed, true);
});

test('fetcher por defecto valida la forma del subyacente antes de salir a red', async () => {
    const { fetchCboeChain } = await import('../lib/market/cboe-options.ts');
    const r = await fetchCboeChain('no es un simbolo valido!');
    assert.equal(r.chain, null);
    assert.equal(r.fetchFailed, true);
});
