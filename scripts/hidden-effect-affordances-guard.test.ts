/**
 * F173+F177: un control que ejecuta un proceso debe decirlo en su
 * etiqueta. Nada de CTAs con pinta informativa («Revisar») que lanzan
 * revisiones ni checkboxes con pinta de preferencia persistente que
 * disparan evaluaciones de una sola vez.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');
const insider = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');

test('el CTA de alertas declara que ejecuta una revisión', () => {
    assert.match(alerts, /Ejecutar revisión/);
    assert.match(alerts, /aria-label=\{`Ejecutar revisión de expectativas de \$\{alert\.symbol\}`\}/);
    assert.doesNotMatch(alerts, />\s*Revisar\s*</);
});

test('la pantalla insider no expone el botón de depuración del aviso Telegram', () => {
    assert.doesNotMatch(insider, /Evaluar aviso Telegram ahora/);
    assert.doesNotMatch(insider, /Avisarme por Telegram/);
    assert.doesNotMatch(insider, /type="checkbox"[^>]*notify/);
});
