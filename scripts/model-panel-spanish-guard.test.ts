/**
 * Guard: el panel del modelo a largo plazo y la oportunidad de mercado no
 * muestran identificadores en ingles/snake_case al usuario (regla de UI en espanol).
 *
 * Ejecutar: node --experimental-strip-types --test scripts/model-panel-spanish-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { metricLabel } from '../lib/research/metric-labels.ts';

const panel = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('drivers, KPIs y entradas faltantes pasan por metricLabel', () => {
    // term = termLabel con el idioma elegido (i18n).
    assert.match(panel, /const term = \(item: string\) => termLabel\(item, locale\)/);
    assert.match(panel, /revenue_drivers\.map\(term\)/);
    assert.match(panel, /kpis\.map\(term\)/);
    assert.match(panel, /missing_inputs\.map\(term\)/);
    assert.match(page, /formula\.missing_inputs\.map\(\(item\) => termLabel\(item, locale\)\)/);
});

test('no queda «Value/share» en la UI y unknown/low/high tienen etiqueta en espanol', () => {
    assert.doesNotMatch(panel, /Value\/share/);
    assert.doesNotMatch(page, /Value\/share/);
    assert.match(page, /unknown: 'desconocido'/);
    assert.match(page, /low: 'baja'/);
});

test('las entradas de modelo mas habituales tienen etiqueta en espanol (no la clave humanizada)', () => {
    // Comportamiento, no texto: se llama a metricLabel. Sin etiqueta propia
    // devolveria el fallback «traceable wacc», que es lo que se veta.
    for (const key of ['traceable_wacc', 'organic_growth', 'share_count', 'working_capital', 'monthly_arpu']) {
        const label = metricLabel(key);
        assert.notEqual(label, key.replaceAll('_', ' '), `${key} sin etiqueta propia`);
        assert.doesNotMatch(label, /_/, `${key}: «${label}» lleva snake_case`);
        assert.equal(metricLabel(key.toUpperCase()), label, `${key}: la clave en mayusculas no encuentra la etiqueta`);
    }
});

test('una clave desconocida se humaniza, nunca se muestra en snake_case', () => {
    assert.equal(metricLabel('clave_nueva_del_backend'), 'clave nueva del backend');
});
