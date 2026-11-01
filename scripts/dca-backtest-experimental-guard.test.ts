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
// El texto vive en el diccionario (es por defecto); el componente lo pinta con t().
const es = JSON.parse(readFileSync('lib/i18n/messages/es/propicks.json', 'utf8')).dcaBacktest;

test('el aviso experimental está visible antes del formulario', () => {
  assert.match(es.experimental, /^Experimental: este backtest simula datos históricos/);
  const notice = source.indexOf("t('propicks.dcaBacktest.experimental')");
  assert.ok(notice > 0, 'falta el aviso experimental');
  assert.ok(notice < source.indexOf('<form onSubmit={run}'), 'el aviso debe ir antes del formulario');
  assert.match(source, /role="note"/);
});

test('el aviso no presenta la simulación como predicción ni consejo', () => {
  assert.match(es.experimental, /No predice resultados futuros/);
  assert.match(es.experimental, /costes, impuestos/);
  assert.match(es.experimental, /No es una recomendación de inversión/);
});
