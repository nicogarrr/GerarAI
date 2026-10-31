/** /taxes: el resumen fiscal (sin-atribuir, método, criterio FX) llega con
 *  claves internas del backend y la vista las traduce vía diccionario i18n.
 *  Tras la migración, los literales viven en
 *  lib/i18n/messages/<locale>/taxes.json; la vista mapea snake_case -> clave. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));
const en = JSON.parse(readFileSync('lib/i18n/messages/en/taxes.json', 'utf8'));

test('F330: las claves de sin-atribuir y el metodo tienen etiqueta en el diccionario', () => {
    // El resumen fiscal llega con claves internas (unattributed_tickers,
    // unattributed_dividends_base) y el id del metodo en minusculas: la UI
    // las mostraba en crudo («UNATTRIBUTED TICKERS []», «Método fifo»).
    assert.equal(es.labels.unattributedTickers, 'Tickers sin atribuir');
    assert.equal(es.labels.unattributedDividendsBase, 'Dividendos sin atribuir');
    assert.match(view, /unattributed_tickers: 'taxes.labels.unattributedTickers'/);
    assert.match(view, /unattributed_dividends_base: 'taxes.labels.unattributedDividendsBase'/);
    assert.match(view, /'unattributed_dividends_base',\s*\n?\s*\]\);/);
    assert.match(view, /'unattributed_tickers', 'ambiguous_cash'\]\)/);
    assert.equal(es.values.methodFifo, 'FIFO');
    assert.match(view, /key === 'method'/);
});

test('F330: los identificadores UNATTRIBUTED:* se traducen conservando el simbolo', () => {
    assert.match(view, /function humanizeUnattributedTicker/);
    assert.match(view, /UNATTRIBUTED:\(\.\+\)/);
    assert.match(view, /taxes\.values\.unattributed/);
    assert.equal(es.values.unattributed, 'Sin atribuir: {symbol}');
});

test('F330: nada de spanglish en las descripciones de la vista fiscal', () => {
    assert.doesNotMatch(view, /Holdings con base de coste/);
    assert.match(es.holdings.description, /Posiciones con base de coste/);
});

test('F-bug6: el criterio FX de valores tiene etiqueta y traduccion en el diccionario', () => {
    // El resumen incluye securities_fx_criterion='dgt_native_gain_sale_date_v1'
    // y la vista lo mostraba en crudo: «Securities fx criterion» (spanglish al
    // humanizar la clave) y el identificador interno como valor.
    assert.equal(es.labels.securitiesFxCriterion, 'Criterio FX en valores');
    assert.match(es.values.securitiesFxDgt, /Ganancia en divisa del valor/);
    assert.match(view, /securities_fx_criterion: 'taxes.labels.securitiesFxCriterion'/);
    assert.match(view, /key === 'securities_fx_criterion'/);
    assert.equal(typeof en.values.securitiesFxDgt, 'string');
});
