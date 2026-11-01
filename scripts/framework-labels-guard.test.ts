/**
 * Guard: cada driver, KPI, unidad economica, segmento, restriccion y etiqueta de
 * data-engine/app/services/company_framework.py tiene traduccion al espanol
 * (las formulas con × / ÷ se traducen termino a termino).
 *
 * Ejecutar: node --experimental-strip-types --test scripts/framework-labels-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: explicit extension for node strip-types.
import { frameworkLabel, frameworkTerm, FRAMEWORK_LABELS } from '../lib/research/framework-terms.ts';

const src = readFileSync('data-engine/app/services/company_framework.py', 'utf8');
const metricLabels = readFileSync('lib/research/metric-labels.ts', 'utf8');

function tupleItems(field: string): string[] {
    const out: string[] = [];
    for (const m of src.matchAll(new RegExp(`${field}=\\(([^)]*)\\)`, 'g'))) {
        for (const q of m[1].matchAll(/"([^"]+)"/g)) out.push(q[1]);
    }
    return out;
}

test('todas las claves del marco tienen etiqueta en espanol', () => {
    const fields = ['revenue_drivers', 'kpis', 'unit_economics', 'segment_model', 'binding_constraints', 'required_fact_metrics'];
    const missing: string[] = [];
    for (const f of fields) {
        for (const key of tupleItems(f)) {
            const inMetric = new RegExp(`^\\s*${key.toLowerCase()}:`, 'm').test(metricLabels) || new RegExp(`^\\s*${key}:`, 'm').test(metricLabels);
            if (!inMetric && frameworkTerm(key) === null) missing.push(`${f}:${key}`);
        }
    }
    assert.deepEqual(missing, []);
});

test('las 12 etiquetas de marco estan traducidas', () => {
    const labels = [...src.matchAll(/\n\s+label="([^"]+)"/g)].map((m) => m[1]);
    assert.ok(labels.length >= 12);
    for (const l of labels) {
        assert.ok(FRAMEWORK_LABELS[l], l);
        assert.notEqual(frameworkLabel(l), l);
    }
});

test('el panel traduce framework.label y binding_constraint', () => {
    const panel = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
    assert.match(panel, /frameworkLabel\(model\.framework\.label\)/);
    assert.match(panel, /termLabel\(model\.market_opportunity\.constraints\.binding_constraint, locale\)/);
});
