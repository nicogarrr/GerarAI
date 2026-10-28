import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const finnhubActions = readFileSync('lib/actions/finnhub.actions.ts', 'utf8');
const freshness = readFileSync('lib/market/quote-freshness.ts', 'utf8');
const marketWorkspace = readFileSync('lib/actions/market-workspace.actions.ts', 'utf8');
const watchlistActions = readFileSync('lib/actions/watchlist.actions.ts', 'utf8');
const headerQuote = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
const proPicks = readFileSync('lib/actions/proPicks.actions.ts', 'utf8');

// F358 (reporte de usuario, 28/09): BN mostraba 36,87 (+0,66%) cuando el
// mercado marcaba 36,43 (-1,19%): la cotizacion de la sesion ANTERIOR se
// servia como actual. Causa: fetchJSON usa force-cache + revalidate; con
// errores sostenidos del proveedor (429 por cuota, F357) Next sirve el
// ultimo valor bueno indefinidamente (stale-while-error) y el fetch
// resuelve 200 con el dato viejo sin que el error llegue al catch.
// El comportamiento temporal se prueba en scripts/quote-freshness.test.ts;
// aqui se blinda que TODAS las rutas de cotizacion pasan por el filtro.
test('F358: toda cotizacion Finnhub se valida por su timestamp (sanitizeFinnhubQuote)', () => {
    assert.match(freshness, /export function sanitizeFinnhubQuote/, 'existe el filtro (modulo puro, testeable)');
    assert.match(freshness, /classifyQuoteKind\(t, nowMs\)/, 'clasifica por semantica de sesion');
    assert.match(freshness, /if \(kind === 'stale'\) return null/, 'stale se rechaza en origen');
    const uses = finnhubActions.match(/\.then\(sanitizeFinnhubQuote\)/g) ?? [];
    assert.ok(uses.length >= 1, 'getStockFinancialDataLight tambien pasa por el filtro (ruta ProPicks)');
    assert.match(finnhubActions, /const quote = sanitizeFinnhubQuote\(data\)/, 'fetchStockQuote pasa por el filtro');
});

test('F358: el fallback Yahoo (sin timestamp) se marca siempre como cierre, nunca live', () => {
    assert.match(freshness, /t: null, kind: 'close'/, 'Yahoo = cierre fechado SIN fecha atribuida');
    assert.match(finnhubActions, /mapBackendYahooQuote\(data\)/, 'fetchStockQuote mapea Yahoo por el filtro puro');
});

test('F358: los consumidores etiquetan el cierre fechado y no lo pintan actual', () => {
    assert.match(marketWorkspace, /sessionDateEt\(quote\.t\)/, 'la ficha research fecha el cierre');
    assert.match(marketWorkspace, /priceKind: quoteLive \? 'live' : price !== null \? 'close' : null/, 'priceKind propagado');
    assert.doesNotMatch(headerQuote, /Precio de fecha desconocida/);
    assert.match(headerQuote, /extendedQuoteLabel\(quote\)/, 'cabecera exige timestamp del payload extendido');
    assert.match(watchlistActions, /priceAsOf = priceKind === 'close'/, 'watchlist fecha el cierre');
});

test('F358: ProPicks no recibe cache obsoleta (sirve el run persistido del embudo)', () => {
    // El path viejo evaluaba tickers en vivo contra Finnhub (riesgo de cache
    // obsoleta); se elimino como codigo muerto. La guarda ahora fija el
    // contrato nuevo: ProPicks sirve el ultimo run persistido del embudo F1
    // y no vuelve a llamar a Finnhub desde el action.
    assert.match(proPicks, /getLatestFunnelPicks\(/, 'ProPicks sirve el run persistido del embudo');
    assert.doesNotMatch(proPicks, /getStockFinancialData(?:Light)?\(/, 'ProPicks no consulta Finnhub en vivo');
    assert.doesNotMatch(proPicks, /getCandles\(/, 'ProPicks no pide velas en vivo');
});
