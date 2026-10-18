// Guard: el monitor denso de watchlist solo pinta datos con fuente propia
// (market_prices), conector publico trazable (NASDAQ) o tesis publicada.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const page = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/watchlist.actions.ts', 'utf8');
const route = readFileSync('data-engine/app/api/routes/watchlist.py', 'utf8');

test('watchlist page consume el endpoint monitor del backend', () => {
    assert.match(actions, /\/api\/watchlist\/monitor\?tickers=/);
    assert.match(page, /getWatchlistMonitor/);
});

test('proximos resultados y chip 52 semanas vienen del monitor, no hardcodeados', () => {
    assert.match(page, /Próx\. resultados/);
    assert.match(page, /Mínimo 52 sem/);
    assert.match(route, /fetch_earnings_range/);
    assert.match(route, /MarketPrice/);
});

test('el recuento sobre/infravaloradas exige tesis publicada con expected_value', () => {
    assert.match(route, /status == "published"/);
    assert.match(route, /expected_value\.isnot\(None\)/);
    assert.match(page, /Según la tesis publicada de K/);
});

test('sin URLs de proveedor construidas a mano en el frontend', () => {
    assert.doesNotMatch(page, /nasdaq\.com|finance\.yahoo\.com/);
});
