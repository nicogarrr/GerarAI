import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const watchlist = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
const research = readFileSync('app/(root)/research/page.tsx', 'utf8');

function assertWatchlistParallelStreaming(watchlist) {
    assert.doesNotMatch(watchlist, /await fetchDatedChanges/);
    assert.doesNotMatch(watchlist, /await getWatchlistMonitor/);
    // #3255 (A9) añade el contexto FX de la cartera en el mismo Promise.all: sigue en paralelo.
    assert.match(watchlist, /Promise\.all\(\[getWatchlistState\(\), searchParams(, getPortfolioFxContext\(userId\))?\]\)/);
    // Las lecturas SE LANZAN como promesas compartidas antes de su join: si
    // volvieran a crearse tras un await o dentro del join, vuelve la cadena.
    const state = watchlist.indexOf('getWatchlistState(), searchParams');
    const datedStart = watchlist.indexOf('const datedChangesPromise = fetchDatedChanges(');
    const monitorStart = watchlist.indexOf('const monitorPromise = getWatchlistMonitor(');
    const join = watchlist.indexOf('const [datedChanges, monitorData');
    // (la promesa de basics por símbolo se construye tras ese batch; el contrato
    // de la cascada es sobre dated changes + monitor, lanzadas ya en vuelo)
    assert.ok(state > -1 && datedStart > state && monitorStart > state, 'dated changes y monitor deben lanzarse tras conocer los símbolos');
    assert.ok(join > datedStart && join > monitorStart, 'las lecturas deben lanzarse ANTES de su join: si no, vuelve la cadena serial');
    // Las dos se lanzan de forma síncrona, una tras otra, y ANTES del await del
    // batch de basics: si un await se cuela entre ellas (o ambas se mueven
    // después del batch), dated/monitor dejan de solaparse con el resto.
    const first = Math.min(datedStart, monitorStart);
    const second = Math.max(datedStart, monitorStart);
    assert.doesNotMatch(watchlist.slice(first, second), /await\s/, 'no puede haber un await entre el lanzamiento de dated changes y el de monitor');
    const basicsStart = watchlist.indexOf('await getResearchCompaniesBasics(');
    assert.ok(basicsStart === -1 || (datedStart < basicsStart && monitorStart < basicsStart), 'dated changes y monitor deben lanzarse antes del await del batch de basics');
    // Default/symbol order streams monitor decorations. Every explicit metric
    // sort (including earnings) still joins the same already-started monitor.
    assert.match(watchlist, /const metricSort = sort !== 'added' && sort !== 'symbol';/);
    assert.match(watchlist, /case 'earnings': return stock\.monitor\?\.next_earnings_date \?\? null;/);
    assert.match(watchlist, /await Promise\.all\(\[metricSort \? datedChangesPromise : Promise\.resolve\(\{\} as DatedMap\), metricSort \? monitorPromise : Promise\.resolve\(\{ items: \{\}, earningsStatus: 'pending' \} as MonitorData\), Promise\.all\(basicsPromises\)\]\)/);
    assert.match(watchlist, /<MonitorStockStream promise=\{monitorPromise\} render=\{render\}/);
}

test('watchlist starts shared reads in parallel, streams default order and awaits monitor for metric sorts', () => {
    assertWatchlistParallelStreaming(watchlist);
});

test('waterfall guard rejects monitor and sorting regressions', () => {
    const mutants = [
        watchlist.replace('const monitorPromise = getWatchlistMonitor(', 'const monitorPromise = await getWatchlistMonitor('),
        watchlist.replace('const monitorPromise = getWatchlistMonitor(', 'await Promise.resolve(); const monitorPromise = getWatchlistMonitor('),
        watchlist.replace('metricSort ? monitorPromise :', 'false ? monitorPromise :'),
        watchlist.replace("sort !== 'added' && sort !== 'symbol'", "sort !== 'added' && sort !== 'symbol' && sort !== 'earnings'"),
        watchlist.replace('promise={monitorPromise}', 'promise={Promise.resolve({items:{}})}'),
        watchlist.replace("case 'earnings': return stock.monitor?.next_earnings_date ?? null;", "case 'earnings': return null;"),
    ];
    for (const mutant of mutants) {
        assert.notEqual(mutant, watchlist, 'mutation must actually change source');
        assert.throws(() => assertWatchlistParallelStreaming(mutant));
    }
});

test('research starts user context before awaiting the dashboard', () => {
    const ctx = research.indexOf('const userContext');
    const dash = research.indexOf('await getResearchDashboard()');
    assert.ok(ctx > 0 && dash > ctx);
    assert.match(research, /await userContext/);
});


test('watchlist does not wait for the slowest extended quote', () => {
    // Contrato reforzado: la cotización extendida (línea decorativa) ya no se
    // espera NI con presupuesto en el render de servidor — cada carga en frío
    // pagaba el tope de 700 ms. La pide el cliente tras el primer pintado.
    assert.doesNotMatch(watchlist, /getExtendedQuote/);
    assert.doesNotMatch(watchlist, /EXTENDED_QUOTE_BUDGET_MS/);
    const client = readFileSync('components/common/ExtendedHoursLine.tsx', 'utf8');
    // 31-oct-2026: la línea sigue pidiéndose en cliente tras el primer
    // pintado, pero las filas de una página viajan en UNA acción batch
    // (medido en prod: 12 POSTs de acción por carga -> 1 por ventana).
    assert.match(client, /batchedSymbol\('extended-quote'/);
    assert.match(client, /getExtendedQuotes\(symbols\)/);
});
