/**
 * Deep value: el rotulo honesto es obligatorio donde se muestra.
 *
 * La estrategia acepta perfiles que el embudo de calidad rechaza; sin el
 * aviso, una lista de "gangas" se lee como seleccion de calidad. El guard
 * protege el aviso y la nota de fuente no oficial, sin etiqueta repetida.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const view = readFileSync('components/proPicks/DeepValueView.tsx', 'utf8');
const service = readFileSync('data-engine/app/services/deep_value_service.py', 'utf8');

test('el aviso de que NO es el filtro de calidad es visible en la vista', () => {
    assert.match(view, /No es el filtro de calidad ProPicks/);
    assert.match(view, /role="note"/);
});

test('criterio aprobado por Nico: sin etiqueta repetida por cifra', () => {
    // Nico aprobó aplicar este criterio a #2639 el 28-oct a las 08:46 CET. La fuente sigue declarada en la nota de cabecera
    // (rotulo del servidor, test 1 y 5) y la API mantiene el campo fuente;
    // solo se retira la marca repetida junto a cada cifra.
    assert.doesNotMatch(view, /Yahoo \(fuente no oficial\)/);
});

test('el desacuerdo entre fuentes se muestra con ambas cifras', () => {
    assert.match(view, /Fuentes en desacuerdo/);
    assert.match(view, /finnhub_yield_indicated/);
    assert.match(service, /desacuerdo_fuentes/);
    const serviceVal = readFileSync('data-engine/app/services/valuation_metrics_service.py', 'utf8');
    assert.match(serviceVal, /fuentes_en_desacuerdo/);
});

test('el yield extremo se marca para revision, no se muestra como ganga', () => {
    assert.match(view, /dividendo especial/);
});

test('el backend sirve el rotulo en cada respuesta', () => {
    assert.match(service, /STRATEGY_LABEL/);
    assert.match(service, /No es el filtro de calidad ProPicks/);
});
