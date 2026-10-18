import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097
import { canonicalRedirectTicker } from '../lib/research/canonical-ticker.ts';

test('redirige el sufijo de mercado al base resuelto', () => {
    assert.equal(canonicalRedirectTicker('SAN.MC', 'SAN'), 'SAN');
    assert.equal(canonicalRedirectTicker('asml.as', 'ASML'), 'ASML');
    assert.equal(canonicalRedirectTicker('AENA.MC', 'AENA'), 'AENA');
});

test('no redirige si es el mismo ticker, no hay resolucion o no es el prefijo', () => {
    assert.equal(canonicalRedirectTicker('BRK.B', 'BRK.B'), null);
    assert.equal(canonicalRedirectTicker('SAN.MC', 'SAN.MC'), null);
    assert.equal(canonicalRedirectTicker('SAN.MC', null), null);
    assert.equal(canonicalRedirectTicker('SAN.MC', 'ITX'), null);
    assert.equal(canonicalRedirectTicker('SAN', 'SAN'), null);
});

test('redirige la clase US con guion (Yahoo/SEC) a la canonica con punto del master', () => {
    assert.equal(canonicalRedirectTicker('BRK-B', 'BRK.B'), 'BRK.B');
    assert.equal(canonicalRedirectTicker('brk-b', 'BRK.B'), 'BRK.B');
    assert.equal(canonicalRedirectTicker('BF-A', 'BF.A'), 'BF.A');
});

test('no redirige variantes que no son la misma clase ni el mismo emisor', () => {
    assert.equal(canonicalRedirectTicker('BRK-B', 'BRK.A'), null);
    assert.equal(canonicalRedirectTicker('BRK-B', 'BRK'), null);
    assert.equal(canonicalRedirectTicker('BTC-USD', 'BTC.USD'), null); // clase >1 letra: fuera
    assert.equal(canonicalRedirectTicker('BRK-B', null), null);
    assert.equal(canonicalRedirectTicker('BRK-B', 'BRK-B'), null);
});
