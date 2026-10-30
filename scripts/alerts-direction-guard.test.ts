/**
 * Guard: la dirección de una alerta de precio no puede contradecir su etiqueta.
 *
 * El diálogo de alta ofrecía «Tipo de alerta» (price_above/price_below/...) y un
 * select de «Operador» independiente con valor inicial '>'. Elegir «Precio por
 * debajo de» sin tocar el operador guardaba rule_type=price_below con
 * condition.operator='>': el motor evalúa el OPERADOR, así que la alerta saltaba
 * cuando el precio SUBÍA, mientras la lista la anunciaba como «precio por debajo
 * de X». Reproducido en fixture: `MSFT: price_below > 9.0` con
 * condition {"operator": ">", "value": 9.0}.
 *
 * Fix: el select de tipo sincroniza la dirección ('>' para price_above, '<' para
 * price_below), el select de operador solo se muestra para price_change (donde la
 * dirección es una elección real) y queda limitado a las dos direcciones que la
 * etiqueta sabe pintar, y el alta deriva el operador del tipo como red de
 * seguridad ante estados viejos.
 *
 * Ejecución: node --experimental-strip-types --test scripts/alerts-direction-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');

describe('alta de alerta: dirección coherente con el tipo', () => {
    it('el select de tipo sincroniza el operador con la dirección del tipo', () => {
        const typeSelect = alerts.indexOf('onValueChange={(value: AlertType) =>');
        assert.ok(typeSelect !== -1);
        const block = alerts.slice(typeSelect, typeSelect + 2000);
        assert.match(block, /value === 'price_above'\s*\?\s*'>'/);
        assert.match(block, /value === 'price_below'\s*\?\s*'<'/);
    });

    it('el alta deriva el operador del tipo (red de seguridad)', () => {
        const submit = alerts.indexOf('await createAlertResult({');
        assert.ok(submit !== -1);
        const block = alerts.slice(submit, submit + 1500);
        assert.match(block, /operator:/);
        assert.match(block, /formData\.type === 'price_above'\s*\?\s*'>'/);
        assert.match(block, /formData\.type === 'price_below'\s*\?\s*'<'/);
    });

    it('el select de operador solo se muestra para price_change', () => {
        assert.match(alerts, /\{formData\.type === 'price_change' && \(\s*<div>\s*<Label htmlFor="operator"/);
    });

    it('el operador de price_change solo admite las direcciones que la etiqueta pinta', () => {
        assert.doesNotMatch(alerts, /Menor o igual \(&lt;=\)/);
        assert.doesNotMatch(alerts, /Mayor o igual \(&gt;=\)/);
        assert.doesNotMatch(alerts, /Igual a \(==\)/);
        assert.match(alerts, /formData\.condition\.operator === '<' \? '<' : '>'/);
    });
});
