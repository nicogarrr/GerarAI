/**
 * Deep value: el rotulo honesto es obligatorio donde se muestra.
 *
 * La estrategia acepta perfiles que el embudo de calidad rechaza; sin el
 * aviso, una lista de "gangas" se lee como seleccion de calidad. El guard
 * bloquea que el aviso o la etiqueta de fuente no oficial desaparezcan.
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

test('el dividendo lleva la etiqueta de fuente no oficial en cada cifra', () => {
    assert.match(view, /fuente no oficial/);
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
