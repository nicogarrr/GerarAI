import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const watchlist = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
const research = readFileSync('app/(root)/research/page.tsx', 'utf8');

test('watchlist starts dated changes, monitor and per-symbol reads together (no serial chain)', () => {
    assert.doesNotMatch(watchlist, /await fetchDatedChanges/);
    assert.doesNotMatch(watchlist, /await getWatchlistMonitor/);
    // #3255 (A9) añade el contexto FX de la cartera en el mismo Promise.all: sigue en paralelo.
    assert.match(watchlist, /Promise\.all\(\[getWatchlistState\(\), searchParams(, getPortfolioFxContext\(userId\))?\]\)/);
    assert.match(watchlist, /Promise\.all\(\[datedChangesPromise, monitorPromise, Promise\.all\(basicsPromises\)(, Promise\.all\(notFoundPromises\))?\]\)/);
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
