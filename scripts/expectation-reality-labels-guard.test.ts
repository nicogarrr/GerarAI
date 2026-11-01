/**
 * Guarda F99/F245: «Expectativa vs realidad» pintaba claves crudas del
 * backend (`pending_actual`, `capital_expenditure`…). Ahora las etiquetas en
 * español cubren TODO el catálogo que el backend emite; estos tests extraen
 * el catálogo de la fuente Python (metric_semantics.py y
 * fundamental_review_service.py) y exigen cobertura, así una métrica o
 * estado nuevo del backend rompe el guard en vez de llegar crudo a la UI.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    EXPECTATION_METRIC_LABELS,
    REVIEW_STATUS_LABELS,
    expectationMetricLabel,
    reviewStatusLabel,
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
} from '../lib/research/expectation-labels.ts';

const COMPONENT = 'components/research/FundamentalModelPanels.tsx';
const SEMANTICS_PY = 'data-engine/app/services/metric_semantics.py';
const REVIEW_PY = 'data-engine/app/services/fundamental_review_service.py';
const REPOSITORY_PY = 'data-engine/app/services/fundamental_model_repository.py';

/** Claves métricas del registro Python: líneas `"clave": MetricSemantics(`. */
function backendMetricKeys(): string[] {
    const source = readFileSync(SEMANTICS_PY, 'utf8');
    return [...source.matchAll(/^\s+"([a-z_]+)": MetricSemantics\(/gm)].map((match) => match[1]);
}

/** Estados que el backend puede devolver: literales de classify + servicio. */
function backendStatuses(): string[] {
    const semantics = readFileSync(SEMANTICS_PY, 'utf8');
    const service = readFileSync(REVIEW_PY, 'utf8');
    const fromClassify = [...semantics.matchAll(/return "([a-z_]+)"/g)].map((match) => match[1]);
    const fromClassifyTuples = [...semantics.matchAll(/return \("([a-z_]+)" if[^\n]+\)/g)].map((match) => match[1]);
    const fromService = [...service.matchAll(/status = "([a-z_]+)"|status="([a-z_]+)"/g)].map((match) => match[1] ?? match[2]);
    return [...new Set([...fromClassify, ...fromClassifyTuples, ...fromService])];
}

void test('el backend emite solo estados con etiqueta en español', () => {
    const statuses = backendStatuses();
    assert.ok(statuses.includes('pending_actual'), 'sonda: el catálogo extraído incluye pending_actual');
    for (const status of statuses) {
        assert.ok(REVIEW_STATUS_LABELS[status], `estado sin etiqueta: ${status}`);
    }
});

/** Métricas de FORECAST_METRICS: pueblan ExpectationReview.metric vía forecast.metric. */
function forecastMetricKeys(): string[] {
    const source = readFileSync(REPOSITORY_PY, 'utf8');
    const block = source.match(/FORECAST_METRICS = \(([^)]*)\)/);
    assert.ok(block, 'sonda: FORECAST_METRICS localizable en el repositorio');
    return [...block[1].matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
}

void test('todas las métricas del registro Python tienen etiqueta en español', () => {
    const metrics = backendMetricKeys();
    assert.ok(metrics.length >= 15, `sonda: se extraen las métricas del registro (${metrics.length})`);
    assert.ok(metrics.includes('capital_expenditure') && metrics.includes('fcf_margin'), 'sonda: métricas del hallazgo presentes');
    for (const metric of metrics) {
        assert.ok(EXPECTATION_METRIC_LABELS[metric], `métrica sin etiqueta: ${metric}`);
    }
});

void test('todas las métricas de FORECAST_METRICS tienen etiqueta en español', () => {
    const metrics = forecastMetricKeys();
    assert.ok(metrics.includes('fcf_per_share'), 'sonda: fcf_per_share presente en FORECAST_METRICS');
    for (const metric of metrics) {
        assert.ok(EXPECTATION_METRIC_LABELS[metric], `métrica de forecast sin etiqueta: ${metric}`);
    }
});

void test('las etiquetas funcionan: conocida traduce, desconocida no se oculta', () => {
    assert.equal(reviewStatusLabel('pending_actual'), 'a la espera de resultados');
    assert.equal(reviewStatusLabel('outside_tolerance'), 'fuera de tolerancia');
    assert.equal(reviewStatusLabel('estado_nuevo_del_backend'), 'estado_nuevo_del_backend', 'estado desconocido se muestra, nunca se oculta');
    assert.equal(reviewStatusLabel(null), 's/d');
    assert.equal(expectationMetricLabel('capital_expenditure'), 'CapEx');
    assert.equal(expectationMetricLabel('fcf_per_share'), 'FCF por acción');
    assert.equal(expectationMetricLabel('fcf_margin'), 'Margen FCF');
    assert.equal(expectationMetricLabel('metrica_nueva'), 'metrica nueva', 'métrica desconocida se humaniza');
    assert.equal(expectationMetricLabel(undefined), 's/d');
});

void test('el componente usa las etiquetas y no puede pintar claves crudas', () => {
    const source = readFileSync(COMPONENT, 'utf8');
    assert.match(source, /reviewStatusLabel\(review\.status, ti\)/, 'estado via helper');
    assert.match(source, /expectationMetricLabel\(review\.metric, ti\)/, 'métrica via helper');
    assert.ok(!source.includes('REVIEW_STATUS_LABELS: Record<string, string> = {'), 'sin mapa local duplicado');
    assert.ok(!/\{review\.metric\}/.test(source), 'ninguna métrica se pinta cruda');
});
