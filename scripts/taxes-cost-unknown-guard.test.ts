import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
// Las etiquetas visibles viven en el diccionario i18n (carril C); el
// componente las referencia por clave. El guard verifica ambos extremos.
const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));

// Claves del resumen fiscal que la UI tiene que traducir (etiqueta + motivo
// N/D). El contrato es la PERTENENCIA de cada clave al Set, no su orden:
// #4827 inserto cancelled_lot entre cost_unknown y missing_fx y rompio un
// assert de adyacencia que no era parte del contrato.
const CLAVES_REQUERIDAS = ['over_sell', 'cost_unknown', 'missing_fx'];

function listKeysDe(componente: string): string[] {
    const match = componente.match(/const listKeys = new Set\(\[([^\]]*)\]\)/);
    assert.ok(match, 'no se encontro const listKeys = new Set([...]) en TaxesView');
    return [...match[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
}

function assertClavesRequeridas(keys: string[]): void {
    for (const clave of CLAVES_REQUERIDAS) {
        assert.ok(keys.includes(clave), `listKeys de TaxesView debe incluir '${clave}'`);
    }
}

test('cost_unknown: el resumen fiscal etiqueta las ventas con coste heredado desconocido', () => {
    // El backend marca summary.cost_unknown cuando el lote vendido arrastra la
    // perdida diferida de una venta descubierta: los totales salen N/D y la UI
    // tiene que decir por que, no mostrar la clave en crudo.
    assert.match(view, /cost_unknown: 'taxes.labels.costUnknown'/);
    assertClavesRequeridas(listKeysDe(view));
    assert.match(view, /taxes\.values\.reasonCostUnknown/);
    assert.equal(esTaxes.labels.costUnknown, 'Ventas con coste heredado desconocido');
    assert.match(esTaxes.values.reasonCostUnknown, /^coste heredado de una venta descubierta/);
});

test('cost_unknown: el guard rechaza la omision de cualquier clave requerida', () => {
    // Controles negativos: si TaxesView pierde cualquiera de las claves
    // requeridas, el guard tiene que fallar nombrando la clave que falta.
    const keys = listKeysDe(view);
    for (const omitida of CLAVES_REQUERIDAS) {
        const incompleto = keys.filter((k) => k !== omitida);
        assert.throws(() => assertClavesRequeridas(incompleto), new RegExp(`'${omitida}'`));
    }
});
