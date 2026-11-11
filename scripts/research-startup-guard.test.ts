import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
test('overview independent reads launch before workspace/market waits and builders', () => {
    const identity = page.indexOf('const company = snapshot.company');
    const barrier = page.indexOf('const [watchlist, viewSettled] = await Promise.all');
    for (const name of ['overviewPerPromise', 'overviewOwnershipPromise', 'overviewHoldingPromise', 'overviewAnalystsPromise', 'overviewKeyStatsPromise']) {
        const launch = page.indexOf(`const ${name}`);
        assert.ok(launch > identity && launch < barrier, name);
        assert.match(page.slice(launch, barrier), /activeView === 'overview'/);
    }
});
test('overview and optional sections stream, while DCA mounting stays untouched', () => {
    assert.match(page, /node: <DeferredResearchSection build=\{buildOverviewContent\}/);
    assert.doesNotMatch(page, /node: await buildOverviewContent/);
    assert.match(page, /node: <DeferredResearchSection build=\{build\} onError=\{onError\}/);
    assert.match(page, /MobileCollapse deferMount[^\n]+DeferredAnalystHistory/);
    assert.match(page, /MobileCollapse deferMount[^\n]+DeferredAnalystTargets initial=\{overviewAnalystsPromise\}/);
    assert.match(page, /<MobileCollapse title=\{t\('research.fichaDcaSignalsTitle'\)\}><Suspense fallback=\{null\}><DcaHitRatesSection ticker=\{ticker\} \/><\/Suspense><\/MobileCollapse>/);
});
