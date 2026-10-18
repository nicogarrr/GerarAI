import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const source = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('inicio preserves watchlist availability instead of silently returning an empty list', () => {
    assert.match(source, /getWatchlistState\(\)\.then\(\(\{ items, unavailable \}\) =>/);
    assert.match(source, /if \(unavailable\) throw new Error\('No se pudo cargar la watchlist'\)/);
    assert.doesNotMatch(source, /\bgetWatchlist\(/);
    assert.match(source, /setWatchlistError\(result\.error\)/);
});

test('inicio watchlist etiqueta los cierres con su fecha, como /watchlist', () => {
    assert.match(source, /priceKind: data\.priceKind/);
    assert.match(source, /priceAsOf: data\.priceAsOf/);
    assert.match(source, /stock\.priceKind === 'close'/);
    assert.match(source, /formatMarketDate\(stock\.priceAsOf\)/);
    assert.match(source, /'Cierre sin fecha de la fuente'/);
});
