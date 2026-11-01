import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * /alerts: el fallo de CARGA se comunica una sola vez (estado inline con
 * Reintentar). El fallo de ALTA con el motor caído (offline) también usa
 * superficie inline DENTRO del diálogo: el toast con acción quedaba
 * inutilizable bajo el modal (el click cerraba el diálogo vía overlay y Tab
 * no alcanzaba el botón dentro del focus-trap de Radix). Borrar y revisar
 * conservan su toast con reintento (no hay modal abierto en esos flujos).
 */
const source = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');

test('la carga fallida no dispara toast además del estado inline', () => {
    const loadBlock = source.match(/const loadAlerts = async \(\) => \{[\s\S]*?\n    \};/);
    assert.ok(loadBlock, 'loadAlerts no encontrado');
    assert.match(loadBlock[0], /setLoadError/);
    assert.doesNotMatch(loadBlock[0], /showErrorToast/);
});

test('el alta offline se reintenta inline dentro del diálogo, sin toast accionable', () => {
    // El catch del alta clasifica: offline -> estado inline; resto -> toast
    // informativo sin acción (duplicados, validación de servidor...).
    assert.match(source, /classifyError\(error\) === 'offline'/);
    assert.match(source, /setCreateError\(getFriendlyErrorMessage\(error\)\)/);
    // La región inline es un role=alert enfocable con su propio Reintentar
    // que relanza el alta; se limpia al reintentar y al cerrar el diálogo.
    assert.match(source, /role="alert"/);
    assert.match(source, /createErrorRef/);
    assert.match(source, /if \(!next\) setCreateError\(null\);/);
    // El alta ya no pasa onRetry al toast: esa acción bajo el modal no era
    // usable (overlay interceptaba el click, focus-trap bloqueaba el Tab).
    const createCatch = source.match(/const handleCreateAlert = async \(\) => \{[\s\S]*?\n    \};/);
    assert.ok(createCatch, 'handleCreateAlert no encontrado');
    assert.doesNotMatch(createCatch[0], /onRetry/);
});

test('borrar y revisar conservan showErrorToast con reintento', () => {
    assert.match(source, /onRetry: \(\) => handleDeleteAlert\(alertId\)/);
    assert.match(source, /onRetry: \(\) => handleReview\(alert\)/);
    assert.match(source, /duplicateMessage: ti\('alerts\.errors\.duplicate'\)/);
});

test('la carga distingue causa probada en servidor, sin inventarla', () => {
    const actions = readFileSync('lib/actions/alerts.actions.ts', 'utf8');
    assert.match(actions, /getUserAlertsResult/);
    // session SOLO desde AuthenticationError local (code AUTH_ERROR), nunca
    // desde un statusCode 401: un 401 del backend no prueba sesión caducada.
    assert.match(actions, /error\.code === 'AUTH_ERROR'\) cause = 'session'/);
    assert.doesNotMatch(actions, /statusCode === 401/);
    assert.match(actions, /statusCode === 403\) cause = 'forbidden'/);
    assert.match(actions, /statusCode === 429\) cause = 'rate'/);
    assert.match(actions, /statusCode >= 500\) cause = 'offline'/);
    assert.match(source, /getUserAlertsResult\(\)/);
    assert.match(source, /alertsLoadErrorSession/);
    assert.match(source, /alertsLoadErrorForbidden/);
    assert.match(source, /alertsLoadErrorRate/);
    // El enlace de re-login solo se ofrece con causa session probada.
    assert.match(source, /cause === 'session' \? \(/);
    // i18n: el literal «Iniciar sesión» vive en messages/<locale>/alerts.json (session.signIn).
    assert.match(source, /alerts\.session\.signIn/);
    assert.doesNotMatch(source, /alertsLoadErrorAuth/);
    // La vista ya no consume la variante que lanza sin causa.
    assert.doesNotMatch(source, /getUserAlerts\(\)/);
});
