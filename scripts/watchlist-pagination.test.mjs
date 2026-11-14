import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const source = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');

test('watchlist quotes only its bounded visible page', () => {
    assert.match(source, /const PAGE_SIZE = 12/);
    assert.match(source, /orderedItems\.slice\(\(page - 1\) \* PAGE_SIZE, page \* PAGE_SIZE\)/);
    // Contrato de streaming (2026-11-14, #5633): sin orden por metrica la
    // pagina NO espera la cadena de cotizacion: pinta cada fila con los
    // basics del master (initialStock) y la cotizacion viva llega por
    // streaming en EntryRowStream. Con orden por metrica se sigue esperando
    // todo antes de ordenar (await sobre entryPromises).
    assert.match(source, /const initialStock = \(item: \(typeof pageItems\)\[number\]/);
    assert.match(source, /: pageItems\.map\(\(item, index\) => initialStock\(item, basicsList\[index\] \?\? null\)\)/);
    assert.match(source, /metricSort\s*\?\s*await Promise\.all\(entryPromises\.map/);
    assert.match(source, /<EntryRowStream\s+promise=\{entryPromises\[index\]\}/);
    assert.doesNotMatch(source, /watchlistItems\.map\(async/);
    assert.match(source, /Number\.isSafeInteger\(requestedPage\)/);
    assert.match(source, /Math\.min\(totalPages, Math\.max\(1,/);
    assert.match(source, /aria-label=\{t\('watchlist\.page\.pagesNav'\)\}/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/watchlist.json', 'utf8')).page.pagesNav, 'Páginas de watchlist');
    assert.match(source, /page - 1/);
    assert.match(source, /page \+ 1/);
});
