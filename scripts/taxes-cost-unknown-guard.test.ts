import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
// Las etiquetas visibles viven en el diccionario i18n (carril C); el
// componente las referencia por clave. El guard verifica ambos extremos.
const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));

test('cost_unknown: el resumen fiscal etiqueta las ventas con coste heredado desconocido', () => {
    // El backend marca summary.cost_unknown cuando el lote vendido arrastra la
    // perdida diferida de una venta descubierta: los totales salen N/D y la UI
    // tiene que decir por que, no mostrar la clave en crudo.
    assert.match(view, /cost_unknown: 'taxes.labels.costUnknown'/);
    assert.match(view, /'over_sell', 'cost_unknown', 'missing_fx'/);
    assert.match(view, /taxes\.values\.reasonCostUnknown/);
    assert.equal(esTaxes.labels.costUnknown, 'Ventas con coste heredado desconocido');
    assert.match(esTaxes.values.reasonCostUnknown, /^coste heredado de una venta descubierta/);
});
