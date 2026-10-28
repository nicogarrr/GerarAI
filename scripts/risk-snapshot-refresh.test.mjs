import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const source = readFileSync('components/risk/RiskDashboardView.tsx', 'utf8');

test('risk refresh replaces the whole snapshot, not only the headline card', () => {
    assert.match(source, /const \[dashboard, setDashboard\] = useState\(initialDashboard\)/);
    assert.match(source, /const next = await getRiskDashboard\(\);\s+setDashboard\(next\)/);
    assert.match(source, /extractPositions\(dashboard\)/);
    assert.match(source, /extractAlerts\(dashboard\)/);
    assert.match(source, /\? dashboard\.base_currency/);
    assert.match(source, /fetchRecord=\{refreshDashboard\}/);
    assert.doesNotMatch(source, /extractPositions\(initialDashboard\)|extractAlerts\(initialDashboard\)/);
});

test('server refresh syncs the snapshot without discarding it on a failed read', () => {
    // La sincronización es un ajuste durante el render (reset al cambiar la
    // prop), equivalente al antiguo efecto [initialDashboard].
    assert.match(source, /prevInitial !== initialDashboard/);
    assert.match(source, /setDashboard\(initialDashboard\);/);
    assert.doesNotMatch(source, /setDashboard\(null\)|catch\s*\([^)]*\)\s*\{\s*setDashboard/);
});
