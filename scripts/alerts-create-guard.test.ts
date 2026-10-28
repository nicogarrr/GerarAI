/**
 * Guard: el botón «Crear alerta» no admite doble click.
 *
 * handleCreateAlert no tenía guard de vuelo y el Button no tenía disabled:
 * dos clicks lanzaban dos createAlert (el borrado ya tenía su patrón
 * `deleting`; el alta no). Ahora `creating` corta la reentrada y deshabilita
 * el botón mientras dura el await.
 *
 * Ejecución: node --experimental-strip-types --test scripts/alerts-create-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');

describe('alta de alerta: sin doble click', () => {
    it('hay estado `creating` y guard de reentrada', () => {
        assert.match(alerts, /const \[creating, setCreating\] = useState\(false\);/);
        assert.match(alerts, /const handleCreateAlert = async \(\) => \{\s*if \(creating\) return;/);
    });
    it('creating se activa antes del await y se libera en finally', () => {
        const handler = alerts.slice(alerts.indexOf('const handleCreateAlert = async'), alerts.indexOf('const handleDeleteAlert = async'));
        const setAt = handler.indexOf('setCreating(true);');
        const firstAwait = handler.indexOf('await ');
        assert.ok(setAt >= 0 && firstAwait > setAt, 'setCreating(true) debe preceder a todo await del alta');
        assert.match(handler.slice(firstAwait), /^await createAlertResult\(\{/);
        assert.match(alerts, /\} finally \{\s*setCreating\(false\);\s*\}/);
    });
    it('el botón se deshabilita mientras crea', () => {
        assert.match(alerts, /<Button onClick=\{handleCreateAlert\} disabled=\{creating\} aria-busy=\{creating\}/);
    });
});

describe('alta de alerta: umbral de precio positivo', () => {
    it('el formulario rechaza precios <= 0 antes de llamar a createAlert', () => {
        const at = alerts.indexOf('El precio debe ser mayor que 0');
        assert.ok(at !== -1 && at < alerts.indexOf('setCreating(true);'));
    });
    it('la server action también lo rechaza', () => {
        const action = readFileSync('lib/actions/alerts.actions.ts', 'utf8');
        assert.match(action, /threshold <= 0/);
    });
});
