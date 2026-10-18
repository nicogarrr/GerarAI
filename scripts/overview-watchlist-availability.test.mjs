import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const component = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
const action = readFileSync('lib/actions/home-overview.actions.ts', 'utf8');
const source = `${component}\n${action}`;

test('inicio preserves watchlist availability instead of silently returning an empty list', () => {
    assert.match(source, /const \{ items, unavailable \} = await getWatchlistState\(\)/);
    assert.match(source, /if \(preview\.unavailable\) throw new Error\('No se pudo cargar la watchlist'\)/);
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
