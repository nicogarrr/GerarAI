/** Inversores: el código interno SIN_DATOS no se pinta crudo en la cartera
 *  declarada (Participación en emisor, total, Peso en cartera): la UI
 *  muestra «N/D», y el peso se calcula valor/total cuando ambos son datos. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const portfolio = readFileSync('app/(root)/inversores/_components/Portfolio.tsx', 'utf8');

test('el fallback visible de un datum ausente es «N/D», no el código SIN_DATOS', () => {
    const datum = portfolio.slice(portfolio.indexOf('export function Datum'), portfolio.indexOf('function derivedWeight'));
    assert.match(datum, /!available\s*\?\s*NA/);
    assert.doesNotMatch(datum, /\?\s*"SIN_DATOS"/);
});

test('la lista vacía y las acciones sin dato tampoco pintan el código crudo', () => {
    assert.match(portfolio, /sin_datos: "Sin datos"/);
    assert.doesNotMatch(portfolio, />SIN_DATOS\{/);
});

test('el peso se deriva de valor/total solo con ambos datos, etiquetado INFERIDO', () => {
    assert.match(portfolio, /function derivedWeight\(/);
    assert.match(portfolio, /\(100 \* value\) \/ totalValue/);
    assert.match(portfolio, /label: "INFERIDO"/);
    assert.match(portfolio, /totalValue > 0/);
    assert.match(portfolio, /<Datum datum=\{weight\} kind="percent" \/>/);
});

test('las comparaciones con la etiqueta del backend (SIN_DATOS) se conservan', () => {
    assert.match(portfolio, /datum\.label !== "SIN_DATOS"/);
    assert.match(portfolio, /weight\.label !== "SIN_DATOS"/);
});
