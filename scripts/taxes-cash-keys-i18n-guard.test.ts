/** /taxes: las claves de caja del resumen (inconsistent_cash_rows,
 *  ambiguous_cash, manual_review) llevan etiqueta y valor traducidos, y la
 *  cantidad de cada posición se formatea con el locale activo («6,0572» en
 *  es-ES). Tras la migración i18n los literales viven en
 *  lib/i18n/messages/<locale>/taxes.json y la vista referencia sus claves. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/taxes.json', 'utf8'));

test('las tres claves de caja tienen etiqueta en castellano en el diccionario', () => {
    assert.equal(es.labels.inconsistentCashRows, 'Filas de caja inconsistentes');
    assert.equal(es.labels.ambiguousCash, 'Tickers con caja ambigua');
    assert.equal(es.labels.manualReview, 'Revisión manual');
    // Y la vista las resuelve desde el diccionario (mapeo snake -> camel).
    assert.match(view, /inconsistent_cash_rows: 'inconsistentCashRows'/);
    assert.match(view, /ambiguous_cash: 'ambiguousCash'/);
    assert.match(view, /manual_review: 'manualReview'/);
});

test('ambiguous_cash se pinta como lista de tickers; inconsistent_cash_rows como filas legibles', () => {
    assert.match(view, /'unattributed_tickers', 'ambiguous_cash'\]\)/);
    assert.match(view, /key === 'inconsistent_cash_rows'/);
    assert.match(view, /function formatInconsistentCashRows/);
    // El importe de una fila ambigua se declara candidato, nunca pago medido.
    assert.match(view, /taxes\.values\.candidate/);
    assert.equal(es.values.candidate, '(candidato)');
    assert.equal(es.values.noneF, 'Ninguna');
    // Divisa ausente o no válida: el importe se omite, nunca se asume EUR.
    assert.match(view, /isValidCurrencyCode\(code\) \? code : null/);
    assert.doesNotMatch(view, /test\(row\.currency\) \? row\.currency\.toUpperCase\(\) : 'EUR'/);
});

test('la cantidad de las posiciones fiscales usa el formato del locale activo', () => {
    assert.match(view, /\['quantity', \(value: unknown\) => f\.formatNumber\(/);
    assert.match(view, /maximumFractionDigits: 6/);
});

test('paridad es/en en las claves de caja usadas por la vista', () => {
    for (const key of ['inconsistentCashRows', 'ambiguousCash', 'manualReview']) {
        assert.equal(typeof en.labels[key], 'string');
        assert.notEqual(en.labels[key], es.labels[key]);
    }
});
