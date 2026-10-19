// Guard: la tira de calendario ocupa el ancho en escritorio (7 columnas, logos
// de 48px) y el enlace de la cabecera de Watchlist tiene texto visible.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const STRIP = readFileSync('components/calendar/EarningsDayStrip.tsx', 'utf8');
const OVERVIEW = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('tira de calendario: 7 columnas y logos de 48px en escritorio, scroll en móvil', () => {
    assert.ok(STRIP.includes('sm:grid sm:grid-cols-7'));
    assert.ok(STRIP.includes('sm:size-12'));
    assert.ok(STRIP.includes('size-9'));
});

test('cabecera de Watchlist con texto visible "Ver todo"', () => {
    assert.ok(OVERVIEW.includes('<span className="whitespace-nowrap">Ver todo</span>'));
});
