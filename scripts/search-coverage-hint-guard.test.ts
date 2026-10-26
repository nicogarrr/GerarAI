// Guard: el buscador etiqueta la cobertura de ficha sin filtrar resultados.
// Causa confirmada 26 oct 2026 contra API Finnhub del plan actual:
// profile2 403 en SAF.PA y SAN.MC (no-US), 200 en META; /search cubre ambas.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: ruta explícita para node --experimental-strip-types.
import { classifyFichaCoverage, EXCHANGE_LABEL_BY_SUFFIX } from '../lib/market/search-coverage.ts';

test('clasifica cobertura con causa confirmada, sin adivinar sufijos desconocidos', () => {
    // US sin sufijo: cubierto por profile2 en el plan actual (META 200).
    assert.equal(classifyFichaCoverage('META', false), 'covered');
    // Bolsa conocida no-US sin master local: plan-limited (SAF.PA 403).
    assert.equal(classifyFichaCoverage('SAF.PA', false), 'plan-limited');
    assert.equal(classifyFichaCoverage('AIR.PA', false), 'plan-limited');
    // Solo sufijos con 403 confirmado: otras bolsas no se etiquetan por
    // extrapolación (sin fuente autoritativa de cobertura).
    assert.equal(classifyFichaCoverage('300183.SZ', false), 'unknown');
    assert.equal(classifyFichaCoverage('TMAS.JK', false), 'unknown');
    // En master local: cubierto aunque profile2 no lo cubra (SAN.MC carga).
    assert.equal(classifyFichaCoverage('SAN.MC', true), 'covered');
    // Sufijo desconocido: no se adivina.
    assert.equal(classifyFichaCoverage('FOO.ZZ', false), 'unknown');
    assert.ok(EXCHANGE_LABEL_BY_SUFFIX.PA && EXCHANGE_LABEL_BY_SUFFIX.MC);
});

test('la búsqueda anota cobertura en ambos caminos (remoto y fallback local)', () => {
    const src = readFileSync('lib/actions/finnhub.actions.ts', 'utf8');
    const block = src.slice(src.indexOf('searchStocksWithStatus = cache'));
    assert.ok(block.includes('classifyFichaCoverage'), 'searchStocksWithStatus debe anotar fichaCoverage');
    assert.ok(block.includes('withCoverage(mergeSpanishListings'), 'camino remoto anotado');
    assert.ok(block.includes('withCoverage(local)'), 'fallback local anotado');
});

test('la paleta comunica la cobertura limitada sin filtrar el resultado', () => {
    const src = readFileSync('components/SearchCommand.tsx', 'utf8');
    assert.ok(src.includes("fichaCoverage === 'plan-limited'"), 'la paleta muestra el aviso de cobertura');
    assert.ok(src.includes('Puede que no tenga ficha'), 'copy hedged: posibilidad, no inservibilidad');
    // Sin filtrado a ciegas: el item sigue seleccionable.
    assert.ok(!src.includes('disabled'), 'los resultados no se deshabilitan');
});
