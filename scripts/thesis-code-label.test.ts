import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Explicit TS extension for strip-types guards.
import { thesisCodeLabel } from '../lib/research/thesis-code-label.ts';
test('HD missing-data tokens are readable without changing evidence or numbers', () => {
 assert.equal(thesisCodeLabel('insufficient_data'), 'datos insuficientes');
 assert.equal(thesisCodeLabel('unknown'), 'sin determinar');
 assert.equal(thesisCodeLabel('free_cash_flow_or_fcf_margin'), 'flujo de caja libre o margen FCF');
 assert.equal(thesisCodeLabel('revenue'), 'Ingresos');
 assert.equal(thesisCodeLabel('traceable_wacc'), 'WACC trazable');
 for (const value of ['https://sec.gov/a_b', '123.4567', 'new_technical_id', 'const x = 1;']) assert.equal(thesisCodeLabel(value), value);
});
