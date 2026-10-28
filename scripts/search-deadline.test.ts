import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error TS5097
import { withFetchDeadline } from '../lib/upstream/fetch-deadline.ts';
// @ts-expect-error TS5097
import { mergeSpanishListings, searchSpanishListings } from '../lib/market/spanish-search.ts';
import { readFileSync } from 'node:fs';

test('headers arrive but body never ends: timeout aborts the transport', async () => {
    let signal: AbortSignal | undefined;
    const start = Date.now();
    await assert.rejects(withFetchDeadline(async (s) => {
        signal = s;
        const response = new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{')); } }));
        return response.json();
    }, 25), { name: 'TimeoutError' });
    assert.equal(signal?.aborted, true);
    assert.ok(Date.now() - start < 1000);
});

test('success and error settle without waiting for deadline', async () => {
    assert.equal(await withFetchDeadline(async () => 42, 1000), 42);
    await assert.rejects(withFetchDeadline(async () => { throw new Error('offline'); }, 1000), /offline/);
});

test('Spanish names, accents and exact symbols resolve reviewed BME identities', () => {
    for (const query of ['Inditex', 'ITX.MC', 'Diseño Textil']) {
        assert.ok(searchSpanishListings(query).some((s) => s.symbol === 'ITX.MC' && s.exchange === 'BME'));
    }
    assert.ok(searchSpanishListings('Telefónica').some((s) => s.symbol === 'TEF.MC'));
    assert.ok(searchSpanishListings('Iberdrola').some((s) => s.symbol === 'IBE.MC'));
    assert.deepEqual(searchSpanishListings('nonexistent-corporation-xyz'), []);
});

test('reviewed snapshot only contains explicit CNMV .MC aliases', () => {
    const source = readFileSync('data-engine/app/services/cnmv_mapping.py', 'utf8');
    const rows = JSON.parse(readFileSync('lib/market/spanish-listings.json', 'utf8')) as {symbol: string}[];
    for (const row of rows) assert.ok(source.includes(`"${row.symbol}"`), row.symbol);
});

test('modal handles rejection, deadline, stale query and close', () => {
    const modal = readFileSync('components/watchlist/WatchlistAddDialog.tsx', 'utf8');
    assert.ok(modal.includes('TickerSearchInput'));
    const shared = readFileSync('components/search/TickerSearchInput.tsx', 'utf8');
    assert.match(shared, /withFetchDeadline\(\(\) => searchStocksWithStatus\(query\), 6000\)/);
    assert.match(shared, /catch \{[\s\S]*setError\(true\)/);
    assert.ok(shared.includes('focused.current'));
    assert.ok(shared.includes('gate.invalidate()'));
    assert.ok((shared.match(/isLatest\(ticket\)/g) ?? []).length >= 3);
});


test('local Spanish substring matches never suppress remote markets', () => {
    const remote = [{symbol: 'SAN', name: 'US test issuer', exchange: 'NYSE', type: 'Stock', isInWatchlist: false}];
    const merged = mergeSpanishListings('SAN', searchSpanishListings('SAN'), remote);
    assert.ok(merged.some((row) => row.symbol === 'SAN'));
    assert.ok(merged.some((row) => row.symbol === 'SAN.MC'));
    const onlySubstring = mergeSpanishListings('NDER', searchSpanishListings('NDER'), remote);
    assert.equal(onlySubstring[0].symbol, 'SAN');
    const exactName = mergeSpanishListings('Inditex', searchSpanishListings('Inditex'), remote);
    assert.equal(exactName[0].symbol, 'ITX.MC');
    assert.equal(mergeSpanishListings('SAN', searchSpanishListings('SAN'), [...remote, ...remote]).filter((r) => r.symbol === 'SAN').length, 1);
});
