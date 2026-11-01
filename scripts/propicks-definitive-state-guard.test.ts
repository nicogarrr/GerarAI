/**
 * Guard de copy DEFINITIVO en las piezas de ProPicks: la ficha de estrategia,
 * el resultado walk-forward y el rebalanceo mensual no pueden volver a copiar un
 * estado intermedio.
 *
 * Antes:
 *  - «Esta estrategia aún no tiene selección ni backtest publicados. En cuanto
 *    estén disponibles aparecerán aquí sus métricas» (promesa de futuro).
 *  - «El backtest por estrategia se publicará cuando existan fundamentales
 *    point-in-time» (el embudo solo guarda un run: no hay tal publicación).
 *  - «Aún no hay snapshot del mes anterior» (GerarAI no guarda histórico de
 *    meses: no es un estado que se resuelva solo).
 *  - WalkForwardResults sin meses: los agregados arrival 0 y se leían como un
 *    «0,00 %» medido.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-definitive-state-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

const factsheet = (readFileSync('components/proPicks/StrategyFactsheet.tsx', 'utf8') + ES_PROPICKS_JSON);
const walkForward = (readFileSync('components/proPicks/WalkForwardResults.tsx', 'utf8') + ES_PROPICKS_JSON);
const rebalance = (readFileSync('components/proPicks/MonthlyRebalanceView.tsx', 'utf8') + ES_PROPICKS_JSON);

describe('ProPicks sin estados intermedios (ficha, backtest, rebalanceo)', () => {
  it('la ficha no promete un backtest por estrategia', () => {
    for (const banned of [
      /aún no tiene selección ni backtest publicados/,
      /En cuanto estén disponibles/,
      /se publicará cuando existan fundamentales/,
      /aparecerán aquí/,
      /mientras tanto, el backtest walk-forward global/,
    ]) {
      assert.ok(!banned.test(factsheet), `la ficha no puede llevar ${banned}`);
    }
  });

  it('la ficha explica por qué no hay cifras y qué haría falta', () => {
    assert.match(factsheet, /Sin métricas de desempeño/);
    // El motivo real: sin fundamentales CON FECHA no hay backtest posible.
    assert.match(factsheet, /con la fecha de cada corte/);
    assert.match(factsheet, /El embudo persiste un único run \(el último\)/);
    assert.match(factsheet, /no se sustituye por una estimación/i);
    // Y declara que el único backtest medido NO es de la estrategia.
    assert.match(factsheet, /Backtesting<\/span>\s*\(momentum 12-1M/);
    assert.match(factsheet, /es independiente de esta estrategia/i);
  });

  it('la ficha muestra dato real: los pesos y el score mínimo del catálogo', () => {
    assert.match(factsheet, /import \{ getStrategyById \} from '@\/lib\/utils\/proPicksStrategies';/);
    assert.match(factsheet, /CATEGORY_KEYS\.map\(\(key\)/);
    assert.match(factsheet, /strategy\.categoryWeights\[key\]/);
    assert.match(factsheet, /Puntuación mínima de entrada:/);
  });

  it('la ficha explica la estrategia no disponible sin prometer nada', () => {
    assert.match(factsheet, /el motor no la ofrece: no hay selección ni métricas que mostrar/);
    assert.ok(!/esta estrategia aún no tiene/i.test(factsheet), 'sin "aún no tiene"');
  });

  it('la ficha nunca pinta el baseline global como métricas de la estrategia', () => {
    assert.match(factsheet, /Backtest global, no de la estrategia/);
    assert.match(factsheet, /Son cifras del baseline walk-forward global/);
  });

  it('walk-forward sin meses declara por qué en vez de pintar ceros', () => {
    assert.match(walkForward, /if \(result\.tablaMensual\.length === 0\) \{/);
    assert.match(walkForward, /Ningún mes se ha simulado/);
    assert.match(walkForward, /al menos 253 cierres anteriores/);
    assert.match(walkForward, /No se muestran ceros/);
  });

  it('el rebalanceo sin mes anterior enseña la selección vigente, no un "entra" de todo', () => {
    assert.ok(!/Aún no hay snapshot del mes anterior/.test(rebalance), 'copy viejo fuera');
    assert.ok(!/aún sin snapshot del mes anterior/.test(rebalance), 'cabecera vieja fuera');
    assert.match(rebalance, /sin comparación con el mes anterior/);
    // Sin snapshot previo la lista no se rotula como entrada: no hay mes con el
    // que comparar, así que poner «Entran» sobre toda la cartera es inventar.
    assert.match(rebalance, /showTone=\{false\}/);
    assert.match(rebalance, /Selección vigente · \{monthLabelEs\(month\)\}/);
    assert.match(rebalance, /no se puede decir qué entra ni qué sale/);
    // Y el motivo es de arquitectura, no de un trabajo futuro.
    assert.match(rebalance, /GerarAI no guarda el histórico de meses/);
  });

  it('el rebalanceo conserva los guardas de export y carga de snapshot', () => {
    assert.match(rebalance, /disabled=\{picksStatus !== 'ready'\}/);
    assert.match(rebalance, /if \(picksStatus !== 'ready'\) return;/);
    assert.match(rebalance, /previousSnapshotError\(parsed, strategyId, month\)/);
  });
});
 it('la referencia de la ficha coincide con la pestaña Selección IA', () => {
    const tabs = (readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8') + ES_PROPICKS_JSON);
    assert.match(tabs, /"picks": "Selección IA"/);
    assert.match(tabs, /t\('propicks\.tabs\.picks'\)/);
    assert.match(tabs, /No valida la selección IA:/);
    assert.match(factsheet, /pestaña «Selección IA»/);
 });
