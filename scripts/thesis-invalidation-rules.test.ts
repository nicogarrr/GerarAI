/**
 * Criterios de invalidación medibles: etiquetas es-ES, parseo del umbral y
 * normalización de la respuesta de la API. Ejecución:
 *   node --experimental-strip-types --test scripts/thesis-invalidation-rules.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  coerceInvalidationRules,
  describeInvalidationRule,
  parseThreshold,
  // @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
} from '../lib/research/thesis-invalidation-rules.ts';

describe('criterios de invalidación medibles', () => {
  it('describe en español con formato es-ES', () => {
    assert.equal(
      describeInvalidationRule({ metric: 'margen_seguridad_pct', operator: '<', threshold: -10 }),
      'margen de seguridad < -10,00 %',
    );
    assert.equal(describeInvalidationRule({ metric: 'precio', operator: '<=', threshold: 1250.5 }), 'precio ≤ 1250,50');
    assert.equal(describeInvalidationRule({ metric: 'metrica:roic', operator: '<', threshold: 0.08 }), 'roic < 0,08');
  });

  it('parsea coma o punto decimal y rechaza lo que no es número', () => {
    assert.equal(parseThreshold('-10,5'), -10.5);
    assert.equal(parseThreshold('0.08'), 0.08);
    assert.equal(parseThreshold('\u221212'), -12);
    assert.equal(parseThreshold('abc'), null);
    assert.equal(parseThreshold(''), null);
    assert.equal(parseThreshold('1e400'), null);
  });

  it('descarta entradas corruptas de la API', () => {
    const rules = coerceInvalidationRules([
      { metric: 'precio', operator: '<', threshold: 250, description: 'Rompe soporte' },
      { metric: 'precio', operator: '=>', threshold: 1 },
      { metric: 7, operator: '<', threshold: 1 },
      'texto',
    ]);
    assert.equal(rules.length, 1);
    assert.equal(rules[0].description, 'Rompe soporte');
    assert.deepEqual(coerceInvalidationRules(null), []);
  });
});
