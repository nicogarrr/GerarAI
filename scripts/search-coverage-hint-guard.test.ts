// Guard: el buscador etiqueta la cobertura de ficha sin filtrar resultados
// y sin extrapolar causa/plan/bolsa: «covered» solo con cobertura local
// verificada; el resto es «unknown» (incluido US no verificado).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: ruta explícita para node --experimental-strip-types.
import { classifyFichaCoverage } from '../lib/market/search-coverage.ts';

test('covered solo con evidencia individual; el resto unknown, sin adivinar', () => {
    // En master local verificado: covered (SAN.MC carga su ficha).
    assert.equal(classifyFichaCoverage('SAN.MC', true), 'covered');
    // Sin evidencia individual: unknown, incluso US o bolsas con 403 observado
    // en otro instrumento (2 GETs no etiquetan una bolsa entera).
    assert.equal(classifyFichaCoverage('META', false), 'unknown');
    assert.equal(classifyFichaCoverage('SAF.PA', false), 'unknown');
    assert.equal(classifyFichaCoverage('AIR.PA', false), 'unknown');
    assert.equal(classifyFichaCoverage('300183.SZ', false), 'unknown');
});

test('la búsqueda anota cobertura en ambos caminos (remoto y fallback local)', () => {
    const src = readFileSync('lib/actions/finnhub.actions.ts', 'utf8');
    const block = src.slice(src.indexOf('searchStocksWithStatus = cache'));
    assert.ok(block.includes('classifyFichaCoverage'), 'searchStocksWithStatus debe anotar fichaCoverage');
    assert.ok(block.includes('withCoverage(mergeSpanishListings'), 'camino remoto anotado');
    assert.ok(block.includes('withCoverage(local)'), 'fallback local anotado');
});

test('la paleta comunica «no comprobada» sin atribuir plan/bolsa y sin filtrar', () => {
    const src = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
    assert.ok(src.includes("fichaCoverage === 'unknown'"), 'la paleta muestra el aviso');
    assert.ok(src.includes('Cobertura de ficha no comprobada'), 'copy sin atribución de causa');
    // gray-600 está prohibido como texto en globals.css (1.7:1, regla #2078).
    assert.ok(!src.includes('text-gray-600">Cobertura'), 'el aviso no usa tinta ilegible');
    assert.ok(!src.includes('plan de datos'), 'sin atribuir causa al plan');
    assert.ok(!src.includes('disabled'), 'los resultados no se deshabilitan');
});
