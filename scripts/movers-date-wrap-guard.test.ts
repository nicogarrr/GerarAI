import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = (readFileSync('components/market/MoversTable.tsx', 'utf8') + readFileSync('app/(root)/screener/page.tsx', 'utf8'));

test('movers: la fecha/hora del precio puede partirse en dos lineas y no ensancha la tabla', () => {
    // E2E prod a 1280px: "del 2026-09-28 · 16:21" en una sola linea empujaba la
    // columna Cambio fuera de la tarjeta (solo se veia "+"). Solo el precio va nowrap
    // (con divisa valida formatPrice, sin ella el numero a pelo - nunca USD).
    assert.match(page, /<span className="whitespace-nowrap">\{isValidCurrencyCode\(row\.currency\) \? formatPrice\(/);
    assert.match(page, /max-w-\[7\.5rem\] text-xs text-gray-500/);
});
