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

test('venta con comisión que no cabe tras abonarla: rechazada ENTERA en el replay, sin mover cash ni lotes', () => {
    // Espejo del chequeo de compra: el replay también impide el sobregiro
    // por comisión (antes solo lo veía el fast-path con el cash ACTUAL).
    const state = computeManualDemoAccount({ EUR: 100, USD: 0 }, [
        fill('Z', 'buy', 10, 10, 100),          // cash 0
        fill('Z', 'sell', 10, 10, 200, 'EUR', 100.01), // 0 + 100 < 100.01
    ]);
    assert.equal(state.cashByCurrency.EUR, 0); // la venta no se aplicó
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 10);
    assert.equal(state.realizedPnlByCurrency.EUR, 0);
    assert.ok(state.violations.some((v) => v.includes('comisión') && v.includes('rechazada entera')));
});

test('frontera exacta: comisión = cash + cobro -> aplica y el cash queda 0, sin violation', () => {
    const state = computeManualDemoAccount({ EUR: 100, USD: 0 }, [
        fill('Z', 'buy', 10, 10, 100),          // cash 0
        fill('Z', 'sell', 10, 10, 200, 'EUR', 100),    // 0 + 100 = 100
    ]);
    assert.equal(state.cashByCurrency.EUR, 0);
    assert.equal(state.positions.length, 0);
    assert.deepEqual(state.violations, []);
});

test('comisión alta pero cubierta: NO es falso positivo (aplica y cuadra)', () => {
    const state = computeManualDemoAccount({ EUR: 100_000, USD: 0 }, [
        fill('Z', 'buy', 10, 10, 100),               // cash 99.900
        fill('Z', 'sell', 10, 100, 200, 'EUR', 500), // 99.900 + 1.000 - 500
    ]);
    assert.equal(state.cashByCurrency.EUR, 100_400);
    assert.equal(state.positions.length, 0);
    assert.deepEqual(state.violations, []);
});

test('cierre de OPCIÓN: la comisión se mide contra el cash tras la prima CON multiplicador', () => {
    const option = (side: 'buy' | 'sell', openClose: 'open' | 'close', contracts: number, premium: number, executedAt: number, fee = 0): Fill => {
        const f = toFill({
            instrument: { kind: 'opcion', contract: { underlying: 'ASTS', expiry: '2027-01-15', callPut: 'call' as const, strike: 30, multiplier: 100, deliverable: 'acciones', adjusted: false }, name: 'ASTS call' },
            side, openClose, quantity: contracts, price: premium, currency: 'EUR', fee, executedAt, clientOrderId: `t${++n}`,
        });
        assert.ok(f, 'fill de opción válido');
        return f;
    };
    // Abre 1 contrato @1 (coste 100): cash 99.900. Cierra @1.5 (prima 150)
    // con fee 100.100: 99.900 + 150 = 100.050 < 100.100 -> violation, sin aplicar.
    const state = computeManualDemoAccount({ EUR: 100_000, USD: 0 }, [
        option('buy', 'open', 1, 1, 100),
        option('sell', 'close', 1, 1.5, 200, 100_100),
    ]);
    assert.equal(state.cashByCurrency.EUR, 99_900);
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 1);
    assert.ok(state.violations.some((v) => v.includes('comisión')));
});

test('sobreventa sin fills parciales: la orden se rechaza ENTERA sin mover cash ni lotes', () => {
    const state = computeManualDemoAccount({ EUR: 10, USD: 0 }, [
        fill('Y', 'buy', 1, 10, 100),
        fill('Y', 'sell', 5, 20, 200),
    ]);
    assert.equal(state.cashByCurrency.EUR, 0); // 10 - 10; la venta no se aplicó
    assert.equal(state.realizedPnlByCurrency.EUR, 0);
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 1);
    assert.ok(state.violations.some((v) => v.includes('rechazada entera')));
});

test('N1: fx EUR->EUR no crea dinero; se rechaza con violation', () => {
    const state = computeManualDemoAccount({ EUR: 100, USD: 0 }, [
        { kind: 'fx', from: 'EUR', to: 'EUR', amountFrom: 100, rate: 2, executedAt: 50, source: 'manual-simulado', clientOrderId: 'fxbad' },
    ]);
    assert.equal(state.cashByCurrency.EUR, 100);
    assert.equal(state.cashByCurrency.USD, 0);
    assert.ok(state.violations.some((v) => v.includes('origen y destino iguales')));
});

test('N2: mismo símbolo en dos divisas son libros separados (no se cruza el FIFO)', () => {
    const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [
        fill('SAN', 'buy', 10, 5, 100, 'EUR'),
        fill('SAN', 'sell', 5, 6, 200, 'USD'), // posición USD inexistente
    ]);
    assert.equal(state.cashByCurrency.EUR, 950);
    assert.equal(state.cashByCurrency.USD, 0); // la venta USD no tocó el libro EUR ni creó USD
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].currency, 'EUR');
    assert.equal(state.positions[0].quantity, 10);
    assert.ok(state.violations.some((v) => v.includes('USD')));
});

test('desempate estable: mismo executedAt se ordena por tiebreak (createdAt persistido), no por array', () => {
    const entries = [
        { ...fill('Z', 'sell', 5, 12, 300), tiebreak: 200 },
        { ...fill('Z', 'buy', 10, 10, 300), tiebreak: 100 },
    ];
    const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, entries);
    // Con tiebreak: compra primero -> venta válida; sin él (orden del array) sería violación.
    assert.equal(state.violations.length, 0);
    assert.equal(state.positions[0].quantity, 5);
    assert.equal(state.realizedPnlByCurrency.EUR, 10);
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
