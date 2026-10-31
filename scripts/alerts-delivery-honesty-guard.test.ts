/**
 * Guarda de honestidad de entregas de alertas (resto de F73): una alerta
 * cuyo canal no tiene registro de entrega no puede mostrarse como
 * «pendiente» — no hay envío en curso, la etiqueta inventaría uno.
 * Ejecución: node --experimental-strip-types --test scripts/alerts-delivery-honesty-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('sin registro de entrega la etiqueta honesta es «sin registro», nunca «pendiente»', () => {
    const manager = source('components/alerts/AlertsManager.tsx');
    assert.ok(!manager.includes("?? 'pendiente'"), 'el fallback no puede inventar un envío pendiente');
    // i18n: la etiqueta «sin registro» vive en messages/<locale>/alerts.json (triggered.noDeliveryRecord).
    assert.ok(manager.includes("?? ti('alerts.triggered.noDeliveryRecord')"), 'ausencia de entrega declarada como ausencia');
});
