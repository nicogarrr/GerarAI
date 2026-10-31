import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
const risk = readFileSync('components/risk/RiskDashboardView.tsx', 'utf8');

test('F306: la cabecera del modelo distingue horizonte de proyección y traduce el estado', () => {
    assert.match(panels, /\{model\.horizon_years\} años de proyección · \{translate\(MODEL_STATUS_LABELS, model\.status, model\.status\)\}/);
    assert.doesNotMatch(panels, /\{model\.horizon_years\} años · \{model\.status\}/);
});

test('F306: el mapa cubre el catálogo cerrado de estados del servicio', () => {
    for (const status of ['ok', 'insufficient_data', 'missing_mandatory_drivers', 'preview_only']) {
        assert.match(panels, new RegExp(`${status}: '`), `falta etiqueta para ${status}`);
    }
});

test('F306: el pie distingue cobertura histórica y respeta la concordancia 1 año/N años', () => {
    assert.match(panels, /Historial disponible: \{model\.historical_review\.years_covered\} \{model\.historical_review\.years_covered === 1 \? 'año' : 'años'\}/);
    assert.match(panels, /frente a los \{model\.horizon_years\} años proyectados/);
    assert.doesNotMatch(panels, /El modelo cubre \{model\.historical_review\.years_covered\} años/);
});

test('F307: el estado sin alertas de /risk solo tranquiliza con estado ok y escribe «de la cartera»', () => {
    // Las cadenas visibles viven en el diccionario i18n (carril C); la vista
    // las referencia por clave. El guard verifica ambos extremos.
    const esAlerts = JSON.parse(readFileSync('lib/i18n/messages/es/risk.json', 'utf8')).alerts;
    assert.match(risk, /status === 'ok'\s*\?\s*t\('risk\.alerts\.emptyOk'\)/);
    assert.equal(esAlerts.emptyOk, 'Sin alertas de concentración o liquidez en los datos calculados.');
    assert.match(risk, /risk\.alerts\.emptyIncomplete/);
    assert.match(esAlerts.emptyIncomplete, /La cobertura incompleta no permite descartar alertas en el resto de la cartera/);
    assert.doesNotMatch(risk, /del cartera/);
    assert.ok(!JSON.stringify(esAlerts).includes('del cartera'), 'concordancia «de la cartera» en el diccionario');
});
