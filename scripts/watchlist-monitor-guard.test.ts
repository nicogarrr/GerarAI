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

test('el recuento sobre/infravaloradas usa el valor justo ÚNICO con su procedencia', () => {
    const service = readFileSync('data-engine/app/services/fair_value_service.py', 'utf8');
    // La tesis solo cuenta si está PUBLICADA y tiene expected_value real.
    assert.match(service, /status == "published"/);
    assert.match(service, /expected_value\.isnot\(None\)/);
    // El monitor no calcula su propio valor justo: lee el servicio compartido.
    assert.match(route, /resolve_fair_values\(db, companies\)/);
    assert.match(route, /"fair_value_source": reading\["source"\]/);
    assert.match(page, /Según el valor justo \(\{fairValueSourceNote\}\)/);
    assert.match(page, /con tesis publicada/);
});

test('inicio y screener leen el mismo valor justo único, con etiqueta', () => {
    const screener = readFileSync('lib/actions/screener.actions.ts', 'utf8');
    const home = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
    assert.match(screener, /\/fair-value`/);
    assert.match(home, /Fuente: \{op\.fairValueLabel\}/);
});

test('sin URLs de proveedor construidas a mano en el frontend', () => {
    assert.doesNotMatch(page, /nasdaq\.com|finance\.yahoo\.com/);
});
