// Guard: el calendario va entre Alertas y Watchlist en Inicio, y la Watchlist
// declara su criterio de orden (las últimas añadidas) cuando recorta la lista.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const PAGE = readFileSync('app/(root)/inicio/page.tsx', 'utf8');
const OVERVIEW = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('la página pasa el calendario como afterAlerts y no lo pinta al final', () => {
    assert.ok(PAGE.includes('afterAlerts='));
    assert.ok(PAGE.indexOf('<EarningsDayStrip />') < PAGE.indexOf('<NewsSection'));
    assert.ok(!/\/>\s*<Suspense fallback=\{null\}>\s*<EarningsDayStrip/.test(PAGE));
});

test('el calendario se pinta después de Alertas y antes de Watchlist', () => {
    const alerts = OVERVIEW.indexOf('2 · Alertas');
    const slot = OVERVIEW.indexOf('{afterAlerts}');
    const watch = OVERVIEW.indexOf('3 · Watchlist');
    assert.ok(alerts > 0 && alerts < slot && slot < watch);
});

test('la watchlist indica que muestra las últimas añadidas', () => {
    assert.ok(OVERVIEW.includes('últimas añadidas de'));
});
