/**
 * Guard de la contabilidad de la demo manual (lib/paper-trading/accounting.ts
 * sobre el contrato lib/paper-trading/types.ts).
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { computeManualDemoAccount } from '../lib/paper-trading/accounting.ts';
// @ts-expect-error -- mismo motivo
import { toFill, type Fill } from '../lib/paper-trading/types.ts';

const accion = (symbol: string) => ({ kind: 'accion' as const, symbol, name: symbol });

let n = 0;
const fill = (symbol: string, side: 'buy' | 'sell', quantity: number, price: number, executedAt: number, currency: 'EUR' | 'USD' = 'EUR', fee = 0): Fill => {
    const f = toFill({ instrument: accion(symbol), side, openClose: side === 'buy' ? 'open' : 'close', quantity, price, currency, fee, executedAt, clientOrderId: `t${++n}` });
    assert.ok(f, 'fill de test válido');
    return f;
};

test('FIFO con ejecutadas desordenadas: ordena por executedAt, no por el array', () => {
    const entries = [
        fill('ASTS', 'sell', 15, 60, 300),
        fill('ASTS', 'buy', 10, 50, 200),
        fill('ASTS', 'buy', 10, 40, 100),
    ];
    const state = computeManualDemoAccount({ EUR: 100_000, USD: 0 }, entries);
    // FIFO: cierra 10@40 y 5@50 -> realizado 10*20 + 5*10 = 250; quedan 5@50.
    assert.equal(state.realizedPnlByCurrency.EUR, 250);
    assert.equal(state.violations.length, 0);
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 5);
    assert.equal(state.positions[0].avgCost, 50);
    // cash: 100000 - 400 - 500 + 900 = 100000
    assert.equal(state.cashByCurrency.EUR, 100_000);
});

test('sobreventa: se cierra solo lo que hay, el exceso no crea dinero y queda registrado', () => {
    const state = computeManualDemoAccount({ EUR: 10, USD: 0 }, [
        fill('Y', 'buy', 1, 10, 100),
        fill('Y', 'sell', 5, 20, 200),
    ]);
    assert.equal(state.cashByCurrency.EUR, 20); // 10 inicial - 10 compra + 20 por la acción real
    assert.equal(state.realizedPnlByCurrency.EUR, 10);
    assert.equal(state.positions.length, 0);
    assert.ok(state.violations.some((v) => v.includes('exceso rechazado')));
});

test('compra sin saldo no se aplica y queda en violations (no hay sobregiro implícito)', () => {
    const state = computeManualDemoAccount({ EUR: 5, USD: 0 }, [fill('X', 'buy', 1, 10, 100)]);
    assert.equal(state.cashByCurrency.EUR, 5);
    assert.equal(state.positions.length, 0);
    assert.ok(state.violations.some((v) => v.includes('insuficiente')));
});

test('multidivisa + fee + conversión fx manual simulada', () => {
    const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [
        { kind: 'fx', from: 'EUR', to: 'USD', amountFrom: 500, rate: 1.2, executedAt: 50, source: 'manual-simulado', clientOrderId: 'fx1' },
        fill('ASTS', 'buy', 2, 100, 100, 'USD', 1),
        fill('ASTS', 'sell', 2, 120, 200, 'USD', 1),
    ]);
    // EUR: 1000 - 500 = 500. USD: 600 - (2*100+1) + (2*120-1) = 638.
    assert.equal(state.cashByCurrency.EUR, 500);
    assert.equal(state.cashByCurrency.USD, 638);
    assert.equal(state.realizedPnlByCurrency.USD, 40);
    assert.equal(state.violations.length, 0);
});

test('toFill rechaza lo que no es una ejecución (precio/cantidad/cero inventado)', () => {
    assert.equal(toFill({ instrument: accion('X'), side: 'buy', openClose: 'open', quantity: 1, price: 0, currency: 'EUR', fee: 0, executedAt: 1, clientOrderId: 'a' }), null);
    assert.equal(toFill({ instrument: accion('X'), side: 'buy', openClose: 'open', quantity: 1.5, price: 10, currency: 'EUR', fee: 0, executedAt: 1, clientOrderId: 'b' }), null);
    assert.equal(toFill({ instrument: accion('X'), side: 'buy', openClose: 'open', quantity: 1, price: 10, currency: 'EUR', fee: 0, executedAt: 1, clientOrderId: '' }), null);
});
