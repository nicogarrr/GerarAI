/**
 * Quick win UX 1: la cabecera de la ficha muestra precio + variación % +
 * sparkline en todas las vistas (desktop y móvil), con degradación honesta
 * (proveedor caído -> bloque omitido, nunca un precio fabricado).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { e2eMarketFixture, E2E_MARKET_FIXTURE_TICKER, isE2EMarketFixtureEnabled } from '../lib/e2e-market-fixture.ts';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { isValidCurrencyCode } from '../lib/format.ts';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const component = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
const actions = readFileSync('lib/actions/market-workspace.actions.ts', 'utf8');

test('la cabecera compone la cotización en todas las vistas', () => {
    assert.match(page, /<CompanyHeaderQuote[^>]*snapshot=\{headerMarket\}/);
    // market ya no se lanza solo en overview: la cabecera lo usa siempre.
    assert.ok(
        !/activeView === 'overview' \? getCompanyMarketSnapshot/.test(page),
        'market sigue limitado a overview: la cabecera quedaría vacía en el resto de vistas',
    );
    // degradación honesta: el fallo del proveedor degrada a null, no a precio inventado.
    assert.match(page, /catch \{\s*headerMarket = null;\s*\}/);
});

test('overview conserva su BackendOffline ante un backend caído', () => {
    // El segundo await de marketPromise en overview debe seguir propagando el
    // rechazo a la ruta estricta: sin ella, una caída del backend pintaría la
    // vista principal vacía en vez del estado reintentable.
    assert.match(page, /market = await marketPromise;/);
    assert.match(page, /isBackendUnavailableError\(error\)/);
    assert.match(page, /return <BackendOffline feature=\{`Datos de mercado de \$\{ticker\}`\}/);
});

test('el fixture E2E solo se activa en la combinación exacta de prueba', () => {
    const enabled = { APP_ENV: 'test', E2E_AUTH_BYPASS: '1', NODE_ENV: 'development' };
    assert.equal(isE2EMarketFixtureEnabled(enabled, E2E_MARKET_FIXTURE_TICKER), true);
    // Tabla de verdad: cualquier desviación cae a la ruta real de proveedores.
    assert.equal(isE2EMarketFixtureEnabled({ ...enabled, APP_ENV: undefined }, E2E_MARKET_FIXTURE_TICKER), false);
    assert.equal(isE2EMarketFixtureEnabled({ ...enabled, APP_ENV: 'production' }, E2E_MARKET_FIXTURE_TICKER), false);
    assert.equal(isE2EMarketFixtureEnabled({ ...enabled, E2E_AUTH_BYPASS: '0' }, E2E_MARKET_FIXTURE_TICKER), false);
    assert.equal(isE2EMarketFixtureEnabled({ ...enabled, E2E_AUTH_BYPASS: undefined }, E2E_MARKET_FIXTURE_TICKER), false);
    assert.equal(isE2EMarketFixtureEnabled({ ...enabled, NODE_ENV: 'production' }, E2E_MARKET_FIXTURE_TICKER), false);
    assert.equal(isE2EMarketFixtureEnabled(enabled, 'AAPL'), false);
    // Y la acción delega la decisión en ese predicado, sin condición propia.
    assert.match(actions, /isE2EMarketFixtureEnabled\(process\.env, normalized\)/);
    assert.ok(
        !/process\.env\.E2E_AUTH_BYPASS === '1'/.test(actions),
        'la acción no debe volver a abrir la condición ancha E2E_AUTH_BYPASS',
    );
    const fixture = e2eMarketFixture(E2E_MARKET_FIXTURE_TICKER);
    assert.equal(fixture.quote.price, 336.56);
    assert.equal(fixture.quote.priceAsOf, null); // cotización "en vivo": sin rótulo de cierre
    assert.equal(fixture.history.length, 40);
});

test('sin divisa verificada no se muestra precio (nunca USD asumido)', () => {
    assert.equal(isValidCurrencyCode('USD'), true);
    assert.equal(isValidCurrencyCode('EUR'), true);
    assert.equal(isValidCurrencyCode(null), false);
    assert.equal(isValidCurrencyCode(''), false);
    assert.equal(isValidCurrencyCode('usd'), false);
    assert.equal(isValidCurrencyCode('US DOLLAR'), false);
    assert.match(component, /isValidCurrencyCode\(currency\)/);
    assert.ok(!/currency\s*=\s*'USD'|currency\s*\?\?\s*'USD'/.test(component), 'la cabecera no debe asumir USD como fallback');
    assert.ok(!component.includes("'en-US'"), 'el USD va en es-ES (Nico 29-oct-2026)');
    assert.match(actions, /researchCompany\?\.currency \|\| profile\?\.currency \|\| null/);
});

test('la variación omite ausencias: línea entera fuera si faltan ambos', () => {
    // Con change y changePercent ausentes (fallback a cierre de vela) NO se
    // pinta «N/D · N/D» bajo el precio: la línea entera se omite y cada valor
    // presente se muestra solo, con separador condicional.
    assert.match(component, /quote.change != null \|\| quote.change_percent != null/);
    assert.match(component, /\.filter\(Boolean\)\s*\.join\(' · '\)/);
    assert.ok(!/\{' · '\}/.test(component), 'queda un separador incondicional');
    assert.match(component, /value == null \|\| !isValidCurrencyCode\(currency\) \? NA : headerMoney/, 'ausencias en la tira de métricas, nunca precio fabricado');
});

test('el color del signo sigue al dato disponible (change ?? changePercent)', () => {
    // Con change ausente y changePercent negativo, el porcentaje no puede
    // salir en verde: el signo se deriva del primer valor presente.
    assert.match(component, /quote\?\.change \?\? quote\?\.change_percent \?\? 0/);
});

test('el precio de cierre se rotula con fecha y lleva gráfico técnico', () => {
    // Sin cotización usable (fallback a vela) no se mezcla la variación del
    // proveedor con ese cierre (F358: la variación solo acompaña a SU
    // cotización, en vivo o en cierre fechado validado).
    assert.match(actions, /const change = dated \? dated\.change : quoteUsable \? quote\?\.d \?\? null : null;/);
    assert.match(actions, /const priceAsOf = quoteLive[\s\S]{0,300}lastClose\?\.date \?\? null;/);
    // Rótulo «Cierre del …» y rango de fechas del sparkline.
    assert.match(component, /extendedQuoteLabel\(quote\)/);
    assert.match(component, /CompanyTechnicalWorkspace snapshot=\{snapshot\}/);
});

test('la variación en divisa usa formatPrice con dígitos significativos (F35), nunca redondeo a 0', () => {
  // TEF 21-oct-2026: variación -0,002 € se pintaba «0 · -0,06 %».
  assert.match(component, /formatPrice/);
  assert.doesNotMatch(component, /formatNumber\(quote\.change/);
  assert.doesNotMatch(component, /formatNumber\(quote\.close_change/);
});
