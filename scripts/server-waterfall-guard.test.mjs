import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const watchlist = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
const research = readFileSync('app/(root)/research/page.tsx', 'utf8');

test('watchlist starts dated changes, monitor and per-symbol reads together (no serial chain)', () => {
    assert.doesNotMatch(watchlist, /await fetchDatedChanges/);
    assert.doesNotMatch(watchlist, /await getWatchlistMonitor/);
    assert.match(watchlist, /Promise\.all\(\[getWatchlistState\(\), searchParams\]\)/);
    assert.match(watchlist, /Promise\.all\(\[datedChangesPromise, monitorPromise\]\)/);
});

test('research starts user context before awaiting the dashboard', () => {
    const ctx = research.indexOf('const userContext');
    const dash = research.indexOf('await getResearchDashboard()');
    assert.ok(ctx > 0 && dash > ctx);
    assert.match(research, /await userContext/);
});


test('watchlist does not wait for the slowest extended quote', () => {
    assert.match(watchlist, /EXTENDED_QUOTE_BUDGET_MS/);
    assert.match(watchlist, /withinBudget\(getExtendedQuote\(item\.symbol\), EXTENDED_QUOTE_BUDGET_MS\)/);
});
