/**
 * Guard: la etiqueta N/D de Cuellos muestra el progreso real de fuentes.
 *
 * Tester 6 (2026-10-19): un tema «N/D · sin evidencia suficiente» mostraba 2
 * evidencias enlazables y no se entendía por qué no era «detectado». El
 * umbral cuenta FUENTES independientes (autores/editores), no evidencias.
 * Contrato: la etiqueta muestra «n de min_sources fuentes independientes» con
 * ambos números reales — min_sources viaja en el payload desde la constante
 * única del backend (MIN_SOURCES en bottleneck_service); nada hardcodeado en
 * la UI ni duplicado en la ruta.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/cuellos-fuentes-etiqueta-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pagina = readFileSync('app/(root)/cuellos/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/bottlenecks.actions.ts', 'utf8');
const ruta = readFileSync('data-engine/app/api/routes/bottlenecks.py', 'utf8');
const servicio = readFileSync('data-engine/app/services/bottleneck_service.py', 'utf8');
const discovery = readFileSync('data-engine/app/services/bottleneck_discovery_service.py', 'utf8');

describe('Cuellos: la etiqueta N/D muestra «n de min_sources fuentes»', () => {
  it('la tarjeta muestra el progreso con los números reales', () => {
    // El texto vive en es/bottlenecks.json (page.sourcesShort) con n y min reales.
    assert.ok(
      pagina.includes("t('bottlenecks.page.sourcesShort', { n: signal.n_sources, min: minSources })"),
      'la etiqueta N/D tiene que mostrar n de min_sources',
    );
    assert.equal(
      JSON.parse(readFileSync('lib/i18n/messages/es/bottlenecks.json', 'utf8')).page.sourcesShort,
      '{n} de {min} fuentes independientes · sin evidencia suficiente',
    );
    assert.ok(pagina.includes('minSources={bottlenecks.min_sources}'), 'la página no pasa min_sources a la tarjeta');
  });

  it('min_sources viaja en el contrato frontend-backend', () => {
    assert.match(actions, /min_sources: number;/);
    assert.match(ruta, /min_sources: int = DETECTION_MIN_SOURCES/);
  });

  it('el umbral tiene un único dueño: MIN_SOURCES del servicio núcleo', () => {
    assert.match(servicio, /^MIN_SOURCES = 2$/m);
    assert.match(ruta, /n_sources >= DETECTION_MIN_SOURCES/);
    assert.ok(!ruta.includes('n_sources >= 2'), 'umbral hardcodeado en la ruta');
    assert.ok(!/^MIN_SOURCES = /m.test(discovery), 'umbral duplicado en el descubrimiento');
    assert.match(discovery, /from app\.services\.bottleneck_service import MIN_SOURCES/);
  });
});
