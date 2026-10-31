// Guard: la tira de calendario ocupa el ancho en escritorio (7 columnas, logos
// de 48px) y el enlace de la cabecera de Watchlist tiene texto visible.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const STRIP = readFileSync('components/calendar/EarningsDayStrip.tsx', 'utf8');
const OVERVIEW = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('tira de calendario: 7 columnas y logos de 48px solo desde 2xl; por debajo, scroll', () => {
    assert.ok(STRIP.includes('2xl:grid 2xl:grid-cols-[repeat(7,minmax(0,1fr))]'));
    assert.ok(STRIP.includes('sm:size-10 2xl:size-12'));
    assert.ok(STRIP.includes('size-9'));
});

test('cabecera de Watchlist con texto visible "Ver todo"', () => {
    assert.ok(OVERVIEW.includes('<span className="whitespace-nowrap">{t(\'home.watchlist.viewAll\')}</span>'));
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.watchlist.viewAll, 'Ver todo');
});
