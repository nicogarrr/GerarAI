import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { looksLikeTicker } from '../lib/research/ticker-shape.ts';

test('tickers reales pasan y rutas de la app no', () => {
    for (const ok of ['AAPL', 'asml', 'BRK.B', 'SAN.MC', 'BTC-USD', '%5EGSPC', 'ASTS', 'AENA']) assert.equal(looksLikeTicker(ok), true, ok);
    for (const bad of ['settings', 'SETTINGS', 'portfolio', 'a b', '%E0%A4%A', '']) assert.equal(looksLikeTicker(bad), false, bad);
});

test('la ficha da 404 normal antes de pedir datos', () => {
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    assert.match(page, /if \(!looksLikeTicker\(rawTicker\)\) notFound\(\);/);
});
