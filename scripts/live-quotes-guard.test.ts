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
import { LIVE_QUOTE_GROUPS, formatQuoteAge, formatQuoteChangePercent, parseYahooQuote, resolveGroupRows, yahooChartRequest } from '../lib/market/live-quotes.ts';

test('catalogo: simbolos unicos, nombre y kind/unit coherentes', () => {
    const seen = new Set<string>();
    for (const group of LIVE_QUOTE_GROUPS) {
        assert.ok(group.specs.length > 0, `grupo ${group.key} vacio`);
        for (const spec of group.specs) {
            assert.ok(spec.symbol.length > 0 && spec.name.trim().length > 0, `spec incompleto: ${JSON.stringify(spec)}`);
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
    const spec = { symbol: 'X', name: 'X', kind: 'accion' as const, unit: 'EUR' as const, decimals: 2 };
    const quote = parseYahooQuote(spec, { regularMarketPrice: 10, regularMarketTime: 100 });
    assert.ok(quote);
    assert.equal(quote.change, null);
    assert.equal(quote.changePercent, null);
});

test('parse: el cierre de referencia sale de las barras diarias, no del meta', () => {
    const spec = { symbol: '^X', name: 'X', kind: 'indice' as const, unit: 'index' as const, decimals: 2 };
    const d1 = 1_700_000_000; // dia 1
    const d2 = d1 + 86_400; // dia 2 (misma zona en el test: UTC por defecto)
    const quote = parseYahooQuote(
        spec,
        { regularMarketPrice: 110, regularMarketTime: d2, exchangeTimezoneName: 'UTC' },
        { timestamps: [d1, d2], closes: [100, 110] },
    );
    assert.ok(quote);
    assert.equal(quote.change, 10);
    assert.equal(quote.changePercent, 10);
    // Sin barras no hay referencia demostrable: cambio N/D, nunca inventado.
    const sinBarras = parseYahooQuote(spec, { regularMarketPrice: 110, regularMarketTime: d2, exchangeTimezoneName: 'UTC' });
    assert.ok(sinBarras);
    assert.equal(sinBarras.change, null);
    assert.equal(sinBarras.changePercent, null);
});

test('parse: precio ausente o roto devuelve null (N/D honesto)', () => {
    const spec = { symbol: 'X', name: 'X', kind: 'materia' as const, unit: 'USD' as const, decimals: 2 };
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

test('resolveGroupRows: una fila N/D conserva la identidad del instrumento', () => {
    // Yahoo fallo para todo el grupo: ni una sola fila pierde nombre/simbolo.
    const rows = resolveGroupRows('indice', [null, null]);
    const specs = LIVE_QUOTE_GROUPS.find((g) => g.key === 'indice')!.specs;
    assert.equal(rows.length, specs.length);
    assert.equal(rows[0].spec.symbol, '^GSPC');
    assert.equal(rows[0].spec.name, 'S&P 500');
    assert.equal(rows[0].quote, null);
    assert.equal(rows[1].spec.symbol, '^IXIC');
});

test('resolveGroupRows: empareja por simbolo aunque el array llegue reordenado', () => {
    const specs = LIVE_QUOTE_GROUPS.find((g) => g.key === 'divisa')!.specs;
    const meta = { regularMarketPrice: 1.12, regularMarketTime: 1_700_000_000, instrumentType: 'CURRENCY' };
    const eurusd = parseYahooQuote(specs[0], meta)!;
    const eurgbp = parseYahooQuote(specs[1], meta)!;
    // Llegan al reves del catalogo: el emparejamiento es por simbolo.
    const rows = resolveGroupRows('divisa', [eurgbp, eurusd, null, null, null]);
    assert.equal(rows[0].quote?.symbol, 'EURUSD=X');
    assert.equal(rows[1].quote?.symbol, 'EURGBP=X');
    assert.equal(rows[2].quote, null);
    assert.equal(rows[2].spec.name, 'GBP/USD');
    // Cotizacion de un simbolo que no esta en el catalogo: no cuela.
    const intruso = parseYahooQuote({ ...specs[0], symbol: 'XXXX=X' }, meta)!;
    const rows2 = resolveGroupRows('divisa', [intruso]);
    assert.ok(rows2.every((r) => r.quote?.symbol !== 'XXXX=X'));
});

test('formatQuoteChangePercent: un cambio real nunca se pinta "+0,00%"', () => {
    // Un pip de cruce (0,004%): con 2 decimales seria "+0,00%" engañoso.
    assert.equal(formatQuoteChangePercent(0.004), '+0,0040');
    assert.equal(formatQuoteChangePercent(-0.0039), '-0,0039');
    // Cero exacto: "+0,00" honesto, sin ampliar.
    assert.equal(formatQuoteChangePercent(0), '+0,00');
    // Magnitudes normales: 2 decimales como siempre.
    assert.equal(formatQuoteChangePercent(0.32), '+0,32');
    assert.equal(formatQuoteChangePercent(-1.62), '-1,62');
});

test('formatQuoteAge: explicita, sin aproximacion implicita', () => {
    // Fronteras minutos: redondeo MARCADO con ~, nunca suelo implícito.
    assert.equal(formatQuoteAge(1800), 'hace ~30 min');
    assert.equal(formatQuoteAge(3540), 'hace ~59 min');
    // 59 min 31 s redondearia a 60 min: se promociona a "hace 1 h".
    assert.equal(formatQuoteAge(3571), 'hace 1 h');
    assert.equal(formatQuoteAge(3600), 'hace 1 h');
    // 90 min y 1 h 59 min: horas+minutos exactos a suelo.
    assert.equal(formatQuoteAge(5400), 'hace 1 h 30 min');
    assert.equal(formatQuoteAge(7140), 'hace 1 h 59 min');
    // Sin "2 h 0 min" redundante; edades largas conservan minutos reales.
    assert.equal(formatQuoteAge(7200), 'hace 2 h');
    assert.equal(formatQuoteAge(180720), 'hace 50 h 12 min');
    // Segundos exactos; cero, negativos (futuro/desfase) y no finitos.
    assert.equal(formatQuoteAge(45), 'hace 45 s');
    assert.equal(formatQuoteAge(0), 'hace 0 s');
    assert.equal(formatQuoteAge(-30), 'hace 0 s');
    assert.equal(formatQuoteAge(NaN), 'hace 0 s');
    assert.equal(formatQuoteAge(Infinity), 'hace 0 s');
});
