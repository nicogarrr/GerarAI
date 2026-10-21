/**
 * Guard del panel /mercados (lib/market/live-quotes.ts):
 *  - el catalogo no tiene simbolos repetidos ni campos vacios (una fila
 *    rota pintaria una cotizacion sin nombre o duplicada);
 *  - parseYahooQuote nunca inventa el cambio: sin cierre previo del
 *    proveedor devuelve change/changePercent a null (la UI pinta N/D);
 *  - la unidad la fija el catalogo (un indice son puntos, F152).
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { LIVE_QUOTE_GROUPS, parseYahooQuote, yahooChartRequest } from '../lib/market/live-quotes.ts';

test('catalogo: simbolos unicos, nombre y kind/unit coherentes', () => {
    const seen = new Set<string>();
    for (const group of LIVE_QUOTE_GROUPS) {
        assert.ok(group.specs.length > 0, `grupo ${group.key} vacio`);
        for (const spec of group.specs) {
            assert.ok(spec.symbol.length > 0 && spec.name.trim().length > 0, `spec incompleto: ${JSON.stringify(spec)}`);
            assert.ok(spec.unitLabel && spec.unitLabel.length > 0, `${spec.symbol} sin unitLabel: la unidad real de la cifra la fija el catalogo`);
            assert.equal(spec.kind, group.key, `${spec.symbol} en grupo equivocado`);
            assert.ok(!seen.has(spec.symbol), `simbolo repetido: ${spec.symbol}`);
            seen.add(spec.symbol);
            if (spec.kind === 'indice' || spec.kind === 'futuro') assert.equal(spec.unit, 'index', `${spec.symbol}: un indice/futuro son puntos`);
            if (spec.kind === 'accion') assert.equal(spec.unit, 'EUR', `${spec.symbol}: acciones ES en EUR`);
            if (spec.kind === 'divisa') assert.equal(spec.unit, 'cruz', `${spec.symbol}: cruz de divisas sin unidad monetaria`);
        }
    }
});

test('parse: sin cierre previo el cambio es null, nunca 0 inventado', () => {
    const spec = { symbol: 'X', name: 'X', kind: 'accion' as const, unit: 'EUR' as const, unitLabel: 'EUR/acción' };
    const quote = parseYahooQuote(spec, { regularMarketPrice: 10, regularMarketTime: 100 });
    assert.ok(quote);
    assert.equal(quote.change, null);
    assert.equal(quote.changePercent, null);
});

test('parse: chartPreviousClose sirve de cierre previo si previousClose falta', () => {
    const spec = { symbol: '^X', name: 'X', kind: 'indice' as const, unit: 'index' as const, unitLabel: 'puntos' };
    const quote = parseYahooQuote(spec, { regularMarketPrice: 110, chartPreviousClose: 100, regularMarketTime: 100 });
    assert.ok(quote);
    assert.equal(quote.change, 10);
    assert.equal(quote.changePercent, 10);
});

test('parse: precio ausente o roto devuelve null (N/D honesto)', () => {
    const spec = { symbol: 'X', name: 'X', kind: 'materia' as const, unit: 'USD' as const, unitLabel: 'USD/barril' };
    assert.equal(parseYahooQuote(spec, null), null);
    assert.equal(parseYahooQuote(spec, {}), null);
    assert.equal(parseYahooQuote(spec, { regularMarketPrice: 0 }), null);
    assert.equal(parseYahooQuote(spec, { regularMarketPrice: Number.NaN }), null);
});

test('request: URL con el simbolo codificado y UA de navegador', () => {
    const { url, init } = yahooChartRequest('EURUSD=X');
    assert.match(url, /finance\/chart\/EURUSD%3DX\?range=2d&interval=1d$/);
    const headers = init.headers as Record<string, string>;
    assert.match(headers['User-Agent'], /Mozilla/);
});
