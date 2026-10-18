import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = (readFileSync('components/market/MoversTable.tsx', 'utf8') + readFileSync('app/(root)/screener/page.tsx', 'utf8'));

test('F331: la tabla de movers cabe en la tarjeta del grid de 3 columnas', () => {
    // A 1366-1920 la tarjeta queda en ~331px y VOLUMEN salía recortado:
    // paddings px-2, nombre truncado a max-w-20 y affordance de scroll como
    // red de seguridad visible.
    assert.doesNotMatch(page, /px-3 py-2 text-right/);
    assert.doesNotMatch(page, /max-w-28 truncate/);
    assert.match(page, /max-w-20 truncate/);
    assert.match(page, /scroll-affordance-x overflow-x-auto \[contain:layout_paint\]/);
});
