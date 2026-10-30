import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = readFileSync('components/risk/RiskDashboardView.tsx', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/risk.json', 'utf8'));
test('empty alerts do not claim safety when missing FX excludes positions', () => {
    assert.match(source, /status === 'ok'/);
    // El literal vive en el diccionario i18n desde la migración del carril C.
    assert.match(es.alerts.emptyIncomplete, /cobertura incompleta no permite descartar alertas/);
    assert.match(source, /risk\.alerts\.emptyIncomplete/);
    assert.doesNotMatch(source, /ninguna posición supera los umbrales/);
});

test('the empty-alerts coverage message follows the refreshed dashboard, not the initial server snapshot', () => {
    assert.match(source, /\bdashboard\?\.status === 'ok'/);
    assert.doesNotMatch(source, /initialDashboard\?\.status/);
});
