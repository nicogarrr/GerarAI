import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const source = readFileSync('components/plan/PlanSetupDialog.tsx', 'utf8');
const action = readFileSync('lib/actions/plan.actions.ts', 'utf8');

test('editing preserves target categories and custom bands supported by the API', () => {
    assert.match(action, /kind: 'ticker' \| 'sector' \| 'asset_class'/);
    assert.match(source, /a\.kind === 'sector' \|\| a\.kind === 'asset_class' \? a\.kind : 'ticker'/);
    assert.match(source, /band_pct: asText\(a\.band_pct\) \|\| '5'/);
    assert.match(source, /kind: row\.kind, label, target_pct: pct, band_pct: band/);
    assert.doesNotMatch(source, /allocations\.push\(\{ kind: 'ticker'/);
    assert.match(source, /row\.kind === 'ticker' \? row\.label\.trim\(\)\.toUpperCase\(\) : row\.label\.trim\(\)/);
});

test('custom bands and duplicate targets are validated before mutation', () => {
    assert.match(source, /band === null \|\| band < 0 \|\| band > 50/);
    assert.match(source, /allocations\.some\(\(allocation\) => allocation\.kind === row\.kind/);
    // El aria-label vive en el diccionario i18n (carril C); el componente lo
    // referencia por clave. El guard verifica ambos extremos.
    assert.match(source, /aria-label=\{t\('plan\.setup\.bandAria'/);
    const esPlan = JSON.parse(readFileSync('lib/i18n/messages/es/plan.json', 'utf8'));
    assert.match(esPlan.setup.bandAria, /^Banda en puntos porcentuales/);
    assert.match(source, /<option value="sector">/);
    assert.match(source, /<option value="asset_class">/);
});
