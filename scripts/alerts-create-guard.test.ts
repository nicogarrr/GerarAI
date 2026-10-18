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
        const setAt = alerts.indexOf('setCreating(true);\n            await createAlert({');
        assert.ok(setAt !== -1, 'setCreating(true) debe ir justo antes de await createAlert');
        assert.match(alerts, /\} finally \{\s*setCreating\(false\);\s*\}/);
    });
    it('el botón se deshabilita mientras crea', () => {
        assert.match(alerts, /<Button onClick=\{handleCreateAlert\} disabled=\{creating\} aria-busy=\{creating\}/);
    });
});
