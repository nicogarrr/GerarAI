/**
 * Guard de la contabilidad paper (lib/paper-trading/accounting.ts):
 * FIFO, cash y realizado deben cuadrar como el extracto de un broker.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { computePaperAccount } from '../lib/paper-trading/accounting.ts';

test('compra y venta FIFO: cash, coste medio y realizado cuadran', () => {
    const state = computePaperAccount(100_000, [
        { symbol: 'ASTS', side: 'buy', quantity: 10, fillPrice: 40 },
        { symbol: 'ASTS', side: 'buy', quantity: 10, fillPrice: 50 },
        { symbol: 'ASTS', side: 'sell', quantity: 15, fillPrice: 60 },
    ]);
    // cash: 100000 - 400 - 500 + 900 = 100000
    assert.equal(state.cash, 100_000);
    // FIFO: se cierran las 10 de 40 y 5 de 50 -> realizado 10*20 + 5*10 = 250
    assert.equal(state.realizedPnl, 250);
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 5);
    assert.equal(state.positions[0].avgCost, 50);
    assert.equal(state.positions[0].realizedPnl, 250);
});

test('simbolo cerrado del todo conserva su realizado y desaparece de posiciones', () => {
    const state = computePaperAccount(1_000, [
        { symbol: 'BBVA.MC', side: 'buy', quantity: 10, fillPrice: 10 },
        { symbol: 'BBVA.MC', side: 'sell', quantity: 10, fillPrice: 12 },
    ]);
    assert.equal(state.positions.length, 0);
    assert.equal(state.realizedPnl, 20);
    assert.equal(state.cash, 1_020);
});

test('operaciones corruptas no descuadran: se ignoran precios y cantidades invalidas', () => {
    const state = computePaperAccount(500, [
        { symbol: 'X', side: 'buy', quantity: 1, fillPrice: 0 },
        { symbol: 'X', side: 'buy', quantity: -3, fillPrice: 10 },
        { symbol: 'X', side: 'sell', quantity: 2, fillPrice: Number.NaN },
        { symbol: 'X', side: 'buy', quantity: 2, fillPrice: 10 },
    ]);
    assert.equal(state.cash, 480);
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 2);
});

test('vender de mas con datos corruptos no rompe: se cierra lo que hay', () => {
    const state = computePaperAccount(0, [
        { symbol: 'Y', side: 'buy', quantity: 1, fillPrice: 10 },
        { symbol: 'Y', side: 'sell', quantity: 5, fillPrice: 20 },
    ]);
    // cash refleja la orden tal cual entro (100 ingresados); la posicion queda a 0.
    assert.equal(state.positions.length, 0);
    assert.equal(state.realizedPnl, 10);
});
