/**
 * Cifras de escenarios: escala inglesa en USD, divisa del emisor desconocida
 * (ADR o divisa inválida) = sin cifra, nunca un número sin moneda.
 * Ejecución: node --experimental-strip-types --test scripts/scenario-format-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { formatScenarioMoney, scenarioCurrency } from '../lib/research/scenario-format.ts';

describe('formato de escenarios', () => {
  it('USD en es-ES con la escala fija y su símbolo (Nico 29-oct-2026)', () => {
    const usd = scenarioCurrency('USD', null);
    assert.equal(formatScenarioMoney(4.87e9, usd, 2), '4,87 mil M\u00a0US$');
    assert.equal(formatScenarioMoney(2.5, usd, 2), '2,50\u00a0US$');
  });
  it('otra divisa de cotización conserva su código', () => {
    const out = formatScenarioMoney(1.2e9, scenarioCurrency('EUR', null), 1);
    assert.match(out ?? '', /€/);
    assert.doesNotMatch(out ?? '', /\$/);
  });
  it('con ADR o divisa inválida no hay cifra', () => {
    assert.equal(scenarioCurrency('USD', 8), null);
    assert.equal(scenarioCurrency('', null), null);
    assert.equal(scenarioCurrency(undefined, null), null);
    assert.equal(formatScenarioMoney(5, null, 2), null);
    assert.equal(formatScenarioMoney(null, scenarioCurrency('USD', null), 2), null);
  });
});
