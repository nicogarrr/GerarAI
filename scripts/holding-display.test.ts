import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error guard importa .ts directamente
import { holdingDisplayMode } from '../lib/portfolio/holding-display.ts';

test('coste desconocido con valor convertido disponible muestra el valor', () => {
    // market_value_base=12345.67, cost_basis_base=null => cost 0, fxMissing true
    assert.equal(holdingDisplayMode({ cost: 0, value: 12345.67, valueMissing: false, fxMissing: true }), 'value');
});
test('coste conocido y conversion completa muestra rentabilidad', () => {
    assert.equal(holdingDisplayMode({ cost: 100, value: 120, valueMissing: false, fxMissing: false }), 'gain');
});
test('sin conversion del valor es N/D, nunca 0', () => {
    assert.equal(holdingDisplayMode({ cost: 0, value: 0, valueMissing: true, fxMissing: true }), 'na');
    assert.equal(holdingDisplayMode({ cost: 100, value: 0, valueMissing: true, fxMissing: true }), 'na');
});
test('valor 0 sin dato no se muestra como 0', () => {
    assert.equal(holdingDisplayMode({ cost: 0, value: 0, valueMissing: false, fxMissing: false }), 'na');
});

// @ts-expect-error guard importa .ts directamente
import { valuationHoldLabel } from '../lib/portfolio/holding-display.ts';

test('valuationHoldLabel muestra motivo y fecha efectiva, nunca una cotización', () => {
    assert.equal(
        valuationHoldLabel({ reason: 'x', effectiveDate: '2025-06-01' }),
        'Valoración pendiente: split del 01/06/2025 sin precio post-split verificado',
    );
    assert.match(valuationHoldLabel({ reason: 'x', effectiveDate: null }), /Valoración pendiente/);
});
