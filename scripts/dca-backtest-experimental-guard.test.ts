/**
 * El backtest DCA es experimental y tiene que decirlo donde se ejecuta.
 *
 * Una simulación sobre precios pasados se lee fácilmente como una promesa de
 * rentabilidad. El aviso debe verse junto al título y antes del formulario,
 * sin depender de que el cálculo termine o de que haya datos.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync('components/proPicks/DcaBacktestPanel.tsx', 'utf8');

test('el aviso experimental está visible antes del formulario', () => {
  const notice = source.indexOf('Experimental: este backtest simula datos históricos');
  assert.ok(notice > 0, 'falta el aviso experimental');
  assert.ok(notice < source.indexOf('<form onSubmit={run}'), 'el aviso debe ir antes del formulario');
  assert.match(source, /role="note"/);
});

test('el aviso no presenta la simulación como predicción ni consejo', () => {
  assert.match(source, /No predice resultados futuros/);
  assert.match(source, /costes, impuestos/);
  assert.match(source, /No es una recomendación de inversión/);
});
