import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { withOptionalBudget } from '../lib/propicks/optional-budget.ts';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');
const action = readFileSync('lib/actions/proPicks.actions.ts', 'utf8');
const page = (readFileSync('app/(root)/propicks/page.tsx', 'utf8') + ES_PROPICKS_JSON);
const tabs = (readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8') + ES_PROPICKS_JSON);
test('el primer render no dispara consultas de overlays', () => {
    assert.match(page, /includeSignalOverlays: false/);
    assert.match(tabs, /if \(activeTab !== 'estrategia'\) return;/);
    assert.match(tabs, /\[activeTab, currentStrategy, cachedStrategyPicks, latestRunAsOf, locale\]/);
    assert.match(action, /options\.includeSignalOverlays === false\s*\? finalists\s*: await attachSignalOverlays/);
    assert.match(action, /return withOptionalBudget\(async \(\) =>/);
    assert.match(action, /\}, finalists, 4_000\)/);
});
test('el presupuesto conserva picks si la fuente no termina', async () => {
    const picks = [{ symbol: 'ASTS', overlays: [] }];
    const start = Date.now();
    assert.equal(await withOptionalBudget(() => new Promise(() => {}), picks, 25), picks);
    assert.ok(Date.now() - start < 1000);
});
test('fuentes rápidas enriquecen; rechazo degrada sin excepción', async () => {
    assert.deepEqual(await withOptionalBudget(async () => ['real'], [], 100), ['real']);
    assert.deepEqual(await withOptionalBudget(async () => { throw new Error('source failure'); }, [], 100), []);
});
