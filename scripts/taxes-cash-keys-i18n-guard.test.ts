/** /taxes: las claves de caja del resumen (inconsistent_cash_rows,
 *  ambiguous_cash, manual_review) llevan etiqueta y valor en español, y la
 *  cantidad de cada posición se formatea es-ES («6,0572», no «6.0572»). */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');

test('las tres claves de caja tienen etiqueta en castellano', () => {
    assert.match(view, /inconsistent_cash_rows: 'Filas de caja inconsistentes'/);
    assert.match(view, /ambiguous_cash: 'Tickers con caja ambigua'/);
    assert.match(view, /manual_review: 'Revisión manual'/);
});

test('ambiguous_cash se pinta como lista de tickers; inconsistent_cash_rows como filas legibles', () => {
    assert.match(view, /'unattributed_tickers', 'ambiguous_cash'\]\)/);
    assert.match(view, /key === 'inconsistent_cash_rows'/);
    assert.match(view, /function formatInconsistentCashRows/);
    // El importe de una fila ambigua se declara candidato, nunca pago medido.
    assert.match(view, /\(candidato\)/);
    assert.match(view, /'Ninguna'/);
});

test('la cantidad de las posiciones fiscales usa formato es-ES', () => {
    assert.match(view, /\['quantity', \(value: unknown\) => formatNumber\(/);
    assert.match(view, /maximumFractionDigits: 6/);
    assert.match(view, /formatNumber, NA, USER_TZ/);
});
