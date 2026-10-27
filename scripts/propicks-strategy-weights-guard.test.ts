/**
 * Guard: los pesos de categoria de las estrategias ProPicks son ratios (0-1, suman 1).
 * La ficha los mostraba todos como «0 %» por formatearlos como si fueran porcentajes.
 * Y la tarjeta de Telegram de Alertas no debe ensenar variables de entorno del servidor.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-strategy-weights-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { PROPICKS_STRATEGIES } from '../lib/utils/proPicksStrategies.ts';

const factsheet = readFileSync('components/proPicks/StrategyFactsheet.tsx', 'utf8');
const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');

describe('pesos de estrategia ProPicks', () => {
  it('la ficha formatea los pesos como ratio (sin fromRatio: false)', () => {
    assert.doesNotMatch(factsheet, /categoryWeights\[key\],\s*\{[^}]*fromRatio:\s*false/);
  });
  it('los pesos de cada estrategia son ratios en [0, 1] que suman 1', () => {
    // Se leen los objetos reales, no el texto: un peso calculado o importado
    // de otro módulo también cuenta.
    const withWeights = PROPICKS_STRATEGIES.filter((s) => s.categoryWeights);
    assert.ok(withWeights.length >= 1, 'ninguna estrategia declara categoryWeights');
    for (const strategy of withWeights) {
      const weights: number[] = Object.values(strategy.categoryWeights ?? {});
      assert.ok(weights.length > 0, `${strategy.id}: categoryWeights vacío`);
      for (const w of weights) {
        assert.ok(Number.isFinite(w) && w >= 0 && w <= 1, `${strategy.id}: peso fuera de ratio (${w})`);
      }
      const total = weights.reduce((a, b) => a + b, 0);
      assert.ok(Math.abs(total - 1) < 1e-6, `${strategy.id}: los pesos suman ${total}, no 1`);
    }
  });
});

describe('Alertas: aviso de Telegram', () => {
  it('no muestra variables de entorno del servidor al usuario', () => {
    assert.doesNotMatch(alerts, /TELEGRAM_(ENABLED|BOT_TOKEN|CHAT_ID)/);
  });
});
