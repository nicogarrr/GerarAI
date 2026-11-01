import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

/**
 * Estados de error coherentes (revisión visual transversal 2026-10-21):
 * - OFFLINE página completa: BackendOffline (ámbar).
 * - OFFLINE sección en cliente: SectionLoadError (mismo ámbar, en línea).
 * - PERMISSION (401/403) y NO_DATOS (vacío) son estados distintos y no
 *   usan ni el rojo destructivo ni el ámbar de fallo.
 * El rojo queda reservado a acciones destructivas.
 */
const section = readFileSync('components/system/SectionLoadError.tsx', 'utf8');
const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');
const propicks = (readFileSync('components/proPicks/ProPicksLoadError.tsx', 'utf8') + ES_PROPICKS_JSON);
const backendOffline = readFileSync('components/system/BackendOffline.tsx', 'utf8');

test('SectionLoadError comparte el acento ámbar de BackendOffline, no rojo', () => {
    assert.match(section, /border-amber-900\/60/);
    assert.match(section, /bg-amber-950\/40/);
    assert.doesNotMatch(section, /red-900|red-950/);
    assert.match(backendOffline, /border-amber-900\/60/);
    assert.match(section, /role="alert"/);
    assert.match(section, /min-h-\[44px\]/);
});

test('Alerts usa el estado de sección compartido, sin caja roja propia', () => {
    assert.match(alerts, /import SectionLoadError from '@\/components\/system\/SectionLoadError';/);
    assert.match(alerts, /<SectionLoadError/);
    assert.doesNotMatch(alerts, /border-red-900\/60 bg-red-950\/20/);
});

test('ProPicks mantiene estados permission/429/4xx distintos y no declara motor caído', () => {
    assert.match(propicks, /statusCode === 401 \|\| statusCode === 403/);
    assert.match(propicks, /statusCode === 429/);
    assert.match(propicks, /Iniciar sesión/);
    assert.doesNotMatch(propicks, /Motor de análisis desconectado/);
});
