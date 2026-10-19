import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// Movidas a vistas de /ownership (Movimientos 13F) por decision de Nico, WhatsApp 2026-10-20 00:59.
const page = readFileSync('app/(root)/ownership/_components/MostBought.tsx', 'utf8');
test('más compradas pagina sin eliminar fechas, procedencia ni compradores', () => {
    assert.match(page, /paginate\(data\.items, pagina, PAGE_SIZE\)/);
    assert.match(page, /paged\.items\.map/);
    assert.doesNotMatch(page, /data\.items\.map/);
    assert.match(page, /<Pagination basePath="\/ownership" page=\{paged\.page\} total=\{paged\.total\} params=\{\{ vista: 'mas-compradas' \}\}/);
    assert.match(page, /data\.report_dates/);
    assert.match(page, /item\.buyers\.map/);
    assert.match(page, /item\.cusip/);
});
test('el nombre del emisor completo es legible en móvil', () => {
    assert.match(page, /break-words text-base font-medium text-gray-100">\{item\.name_of_issuer\}/);
    assert.match(page, /flex flex-col items-start justify-between gap-3 sm:flex-row/);
    assert.doesNotMatch(page, /truncate text-base/);
});
