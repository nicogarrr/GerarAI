/**
 * Diario ↔ operaciones: textos es-ES de la operación y del valor justo del día.
 *   node --experimental-strip-types --test scripts/journal-trade.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { dayEs, describeFairValue, describeTrade } from '../lib/research/journal-trade.ts';

describe('diario enlazado a operaciones', () => {
  it('describe la operación en español', () => {
    assert.equal(
      describeTrade({ id: 1, trade_date: '2026-03-12', action: 'buy', quantity: 10, price: 70.5, currency: 'USD' }),
      'Compra 10 @ 70,50 USD · 12/03/2026',
    );
    assert.equal(dayEs('2026-03-12'), '12/03/2026');
    assert.equal(dayEs(null), 's/d');
  });

  it('describe el valor justo del día con su procedencia y margen', () => {
    assert.equal(
      describeFairValue({
        value: 90, source: 'tesis', version: 1, as_of: '2026-01-10', stale: false,
        label: 'Tesis publicada v1', margin_vs_trade_price: 0.25, note: null,
      }),
      'Valor justo ese día: 90,00 (Tesis publicada v1, 10/01/2026) · margen +25,0 %',
    );
  });

  it('sin valoración previa o con divisa distinta lo dice, sin inventar', () => {
    assert.match(describeFairValue(null), /sin valoración previa/);
    const text = describeFairValue({
      value: 80, source: 'motor', version: 2, as_of: null, stale: false, label: 'Motor de valoración v2',
      margin_vs_trade_price: null, note: 'divisa distinta, no se calcula el margen.',
    });
    assert.match(text, /divisa distinta/);
    assert.doesNotMatch(text, /margen [+-]/);
  });
});
