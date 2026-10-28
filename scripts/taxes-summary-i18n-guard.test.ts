import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');

test('F330: las claves de sin-atribuir y el metodo tienen etiqueta y formato en espanol', () => {
    // El resumen fiscal llega con claves internas (unattributed_tickers,
    // unattributed_dividends_base) y el id del metodo en minusculas: la UI
    // las mostraba en crudo («UNATTRIBUTED TICKERS []», «Método fifo»).
    assert.match(view, /unattributed_tickers: 'Tickers sin atribuir'/);
    assert.match(view, /unattributed_dividends_base: 'Dividendos sin atribuir'/);
    assert.match(view, /'unattributed_dividends_base',\s*\n\s*\]\);/);
    assert.match(view, /'unattributed_tickers', 'ambiguous_cash'\]\)/);
    assert.match(view, /fifo: 'FIFO'/);
    assert.match(view, /key === 'method'/);
});

test('F330: los identificadores UNATTRIBUTED:* se traducen conservando el simbolo', () => {
    assert.match(view, /function humanizeUnattributedTicker/);
    assert.match(view, /UNATTRIBUTED:\(\.\+\)/);
    assert.match(view, /Sin atribuir: \$\{match\[1\]\}/);
});

test('F330: nada de spanglish en las descripciones de la vista fiscal', () => {
    assert.doesNotMatch(view, /Holdings con base de coste/);
    assert.match(view, /Posiciones con base de coste/);
});

test('F-bug6: el criterio FX de valores tiene etiqueta y traduccion en espanol', () => {
    // El resumen incluye securities_fx_criterion='dgt_native_gain_sale_date_v1'
    // y la vista lo mostraba en crudo: «Securities fx criterion» (spanglish al
    // humanizar la clave) y el identificador interno como valor.
    assert.match(view, /securities_fx_criterion: 'Criterio FX en valores'/);
    assert.match(view, /dgt_native_gain_sale_date_v1: 'Ganancia en divisa del valor/);
    assert.match(view, /key === 'securities_fx_criterion'/);
});
