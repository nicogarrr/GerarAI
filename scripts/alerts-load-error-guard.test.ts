import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * /alerts: el fallo de CARGA se comunica una sola vez (estado inline con
 * Reintentar); los fallos de MUTACIÓN conservan su toast porque no tienen
 * otra superficie de feedback.
 */
const source = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');

test('la carga fallida no dispara toast además del estado inline', () => {
    const loadBlock = source.match(/const loadAlerts = async \(\) => \{[\s\S]*?\n    \};/);
    assert.ok(loadBlock, 'loadAlerts no encontrado');
    assert.match(loadBlock[0], /setLoadError/);
    assert.doesNotMatch(loadBlock[0], /showErrorToast/);
});

test('crear, borrar y revisar conservan showErrorToast con reintento', () => {
    const mutations = source.match(/showErrorToast\(error, \{[\s\S]*?\}\);/g) ?? [];
    assert.ok(mutations.length >= 3, `esperados >=3 toasts de mutación, hay ${mutations.length}`);
    assert.match(source, /duplicateMessage: 'Ya tienes esta alerta configurada.'/);
});
