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
    const wl = JSON.parse(readFileSync('lib/i18n/messages/es/watchlist.json', 'utf8')).page;
    assert.ok(page.includes("t('watchlist.page.sort.earnings')") && wl.sort.earnings === 'Próx. resultados');
    assert.ok(page.includes("t('watchlist.page.low52')") && wl.low52 === 'Mínimo 52 sem');
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
    assert.match(page, /t\('watchlist\.page\.fairValue\.summary', \{ source: fairValueSourceNote,/);
    const fv = JSON.parse(readFileSync('lib/i18n/messages/es/watchlist.json', 'utf8')).page.fairValue;
    assert.match(fv.summary, /^Según el valor justo \(\{source\}\)/);
    assert.match(fv.byThesis, /con tesis publicada/);
});

test('inicio y screener leen el mismo valor justo único, con etiqueta', () => {
    const screener = readFileSync('lib/actions/screener.actions.ts', 'utf8');
    const home = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
    assert.match(screener, /\/fair-value`/);
    assert.match(home, /home\.opportunities\.source/);
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.opportunities.source, 'Fuente: {label}');
});

test('sin URLs de proveedor construidas a mano en el frontend', () => {
    assert.doesNotMatch(page, /nasdaq\.com|finance\.yahoo\.com/);
});

test('el monitor no bloquea el primer byte salvo ordenación por resultados', () => {
    // Medido en prod: TTFB de /watchlist ~2-20 s (la cola externa del
    // calendario, deadline 8 s, iba dentro del render). El monitor solo se
    // espera cuando la ordenación lo necesita; el resto llega por streaming.
    assert.match(page, /const monitorUpfront = sort === 'earnings'/);
    assert.match(page, /const monitorData = monitorUpfront \? await monitorPromise : null/);
    assert.doesNotMatch(page, /await Promise\.all\(\[datedChangesPromise, monitorPromise/);
    // Las piezas densas (resumen valor justo, chip 52 sem, próx. resultados)
    // van en boundaries de streaming sobre la promesa compartida.
    for (const component of ['MonitorFairValueSummary', 'MonitorLow52Badge', 'MonitorEarningsDd', 'MonitorEarningsTableCell']) {
        assert.match(page, new RegExp(`<Suspense[^>]*>[\\s\\S]{0,200}<${component} `), `${component} debe ir en Suspense`);
    }
});

test('los fallbacks del monitor muestran espera, nunca N/D fabricado', () => {
    // N/D significa «sin dato»; mientras el monitor está en vuelo el dato
    // puede existir, así que el fallback es espera («…» con aria-busy) o nada.
    const fallbacks = [...page.matchAll(/fallback=\{([^}]*)\}/g)].map((m) => m[1]);
    assert.ok(fallbacks.length >= 4, 'debe haber fallbacks de Suspense');
    assert.doesNotMatch([...page.matchAll(/fallback=\{<dd[\s\S]*?\}/g)].map((m) => m[0]).join(''), /\{NA\}/);
    assert.doesNotMatch([...page.matchAll(/fallback=\{<TableCell[\s\S]*?\}/g)].map((m) => m[0]).join(''), /\{NA\}/);
});
