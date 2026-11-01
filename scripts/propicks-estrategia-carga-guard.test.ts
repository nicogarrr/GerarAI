/**
 * Guard: la pestaña «Estrategia y rebalanceo» no muestra un resultado de 0
 * mientras carga o tras un error.
 *
 * Reproducido (Tester 6, 2026-10-19): la pestaña decía «0 valores vigentes»
 * y «El embudo no devolvió ninguna selección» mientras Selección IA mostraba
 * 9 picks DEL MISMO run, y a la vez «Cargando los picks de esta estrategia…».
 * Causa: MonthlyRebalanceView recibe currentPicks=[] durante la carga/error y
 * renderizaba el recuento y el estado vacío como si fueran el resultado.
 *
 * Contrato: el recuento «N valores vigentes» y el bloque de resultados (aviso
 * de sin-comparación, selección vigente, entran/salen, se mantienen) solo se
 * renderizan con picksStatus === 'ready'; la carga muestra solo la tarjeta de
 * carga y el error solo la tarjeta de error.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-estrategia-carga-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const view = readFileSync('components/proPicks/MonthlyRebalanceView.tsx', 'utf8');
const esRebalance = JSON.parse(readFileSync('lib/i18n/messages/es/propicks.json', 'utf8')).rebalance;

describe('ProPicks: Estrategia no pinta un 0 mientras carga', () => {
  it('el recuento de valores vigentes existe solo con picks listos', () => {
    assert.match(
      view,
      /picksStatus === 'ready'\s*\?\s*t\('propicks\.rebalance\.activeCount', \{\s*count: formatNumber\(currentPicks\.length/,
      '«N valores vigentes» tiene que estar condicionado a picksStatus ready',
    );
    assert.equal(esRebalance.activeCount, '{count} valores vigentes');
    assert.ok(view.includes("t('propicks.rebalance.loadingValues')"), 'falta el texto de carga del recuento');
    assert.equal(esRebalance.loadingValues, 'cargando valores…');
    assert.ok(view.includes("t('propicks.rebalance.valuesUnavailable')"), 'falta el texto de error del recuento');
    assert.equal(esRebalance.valuesUnavailable, 'valores no disponibles');
  });

  it('el aviso de sin-comparación y los resultados solo se pintan en ready', () => {
    assert.match(
      view,
      /\{picksStatus === 'ready' && !diff\.hasPrevious && \(/,
      'el aviso ámbar se pintaba también durante la carga',
    );
    assert.match(
      view,
      /\{picksStatus !== 'ready' \? null : !diff\.hasPrevious \? \(/,
      'el bloque de resultados (selección vigente / entran-sale) se pintaba durante la carga o el error',
    );
  });

  it('la carga y el error conservan sus tarjetas propias', () => {
    assert.match(view, /picksStatus === 'loading' && \(/);
    assert.match(view, /picksStatus === 'error' && \(/);
  });
});
