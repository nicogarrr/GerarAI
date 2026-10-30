/**
 * Guard F311: «Posiciones fiscales» nunca muestra importes crudos
 * («3589.265983»). Las tres columnas monetarias pasan por formatMoney en
 * es-ES con la divisa de la propia fila; RecordList aplica formatColumns
 * antes de caer al String(value) genérico.
 * Ejecución: node --experimental-strip-types --test scripts/taxes-holdings-money-format-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097
import { TAX_HOLDING_MONEY_COLUMNS, formatHoldingCell, formatHoldingMoney } from '../lib/taxes/holding-money.ts';

void test('comportamiento: importes es-ES con divisa de la fila', () => {
    // es-ES agrupa millares a partir de 5 cifras (CLDR minimumGroupingDigits=2)
    assert.equal(formatHoldingMoney(3589.265983, 'EUR'), '3.589,27 €');
    assert.equal(formatHoldingMoney(123456.789, 'EUR'), '123.456,79 €');
    assert.equal(formatHoldingMoney(-92.927388, 'EUR'), '-92,93 €');
    assert.equal(formatHoldingMoney('2159.73', 'USD'), '2.159,73 US$');
    assert.equal(formatHoldingMoney(null, 'EUR'), 'N/D');
    assert.equal(formatHoldingMoney(10, 'euro'), '10,00 €', 'divisa inválida cae a EUR, nunca rompe el formato');
    assert.deepEqual([...TAX_HOLDING_MONEY_COLUMNS].sort(), ['cost_basis', 'market_value', 'unrealized_pnl']);
});

void test('RecordList aplica formatColumns antes del fallback genérico', () => {
    const views = readFileSync('components/data/RecordViews.tsx', 'utf8');
    assert.match(views, /formatColumns\?: Record<string, \(value: unknown, record: DataRecord\) => string>/);
    const cell = views.indexOf('const format = formatColumns?.[column];');
    const fallback = views.indexOf('formatRecordValue(record[column]);', cell);
    assert.ok(cell > -1 && fallback > cell, 'el formateador de columna se consulta antes del String(value)');
});

void test('TaxesView cablea las tres columnas monetarias con la divisa de la fila', () => {
    const taxes = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
    assert.match(taxes, /TAX_HOLDING_MONEY_COLUMNS\.map/);
    assert.match(taxes, /formatHoldingCell\(column, value, record\)/);
    assert.match(taxes, /formatColumns=\{Object\.fromEntries/);
});

void test('B9: base de coste 0 con cantidad > 0 es N/D (no coste real), y la plusvalia latente tambien', () => {
    const sinCoste = { quantity: 10, cost_basis: 0, currency: 'EUR' };
    assert.equal(formatHoldingCell('cost_basis', 0, sinCoste), 'N/D');
    assert.equal(formatHoldingCell('unrealized_pnl', 1500, sinCoste), 'N/D');
    // el valor de mercado no depende de la base
    assert.equal(formatHoldingCell('market_value', 1500, sinCoste), '1.500,00\u00a0€');
    // con coste real todo se pinta
    const conCoste = { quantity: 10, cost_basis: 1000, currency: 'EUR' };
    assert.equal(formatHoldingCell('cost_basis', 1000, conCoste), '1.000,00\u00a0€');
    assert.equal(formatHoldingCell('unrealized_pnl', 500, conCoste), '500,00\u00a0€');
    // cantidad 0 con coste 0: no se afirma ausencia
    assert.equal(formatHoldingCell('cost_basis', 0, { quantity: 0, cost_basis: 0 }), '0,00\u00a0€');
});
