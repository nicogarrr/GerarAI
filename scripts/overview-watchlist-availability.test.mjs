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
    // Contrato F358 ampliado (19 oct 2026, CGEO.L): la vista previa del
    // inicio usa el MISMO cierre datado que /watchlist, Movers y Mercado
    // (/api/market/changes) salvo cotización realmente viva — antes se
    // quedaba con el cierre de la cadena Yahoo y mostraba otra fecha y
    // otro cambio para el mismo símbolo.
    assert.match(source, /fetchDatedChanges\(pageItems\.map/);
    assert.match(source, /data\.priceKind === 'live' \? undefined : datedChanges\[data\.symbol\]/);
    assert.match(source, /priceKind: dated \? 'close' : data\.priceKind/);
    assert.match(source, /priceAsOf: dated \? dated\.date : data\.priceAsOf/);
    assert.match(source, /stock\.priceKind === 'close'/);
    assert.match(source, /formatMarketDate\(stock\.priceAsOf\)/);
    assert.match(source, /home\.watchlist\.closeNoDate/);
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.watchlist.closeNoDate, 'Cierre sin fecha de la fuente');
});
