/**
 * Guard de las server actions de la cuenta demo manual
 * (lib/actions/manual-demo.actions.ts): auth, validación, idempotencia,
 * concurrencia por versión, multidivisa y opciones, ejecutando el código
 * REAL de las actions sobre modelos en memoria (loader co-ubicado).
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-actions.guard.test.ts
 */
import { beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./manual-demo-guard.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
const actions = await import('../lib/actions/manual-demo.actions.ts');
const modelStub = (await import('@/database/models/manual-demo.model')) as unknown as {
    __reset(): void;
    __failNextVersionUpdates(n: number): void;
    __counts(): { accounts: number; trades: number };
};
const connStub = (await import('@/database/mongoose')) as unknown as { __setStartSessionError(e: unknown): void };

const USER = { id: 'guard-user-1', email: 'guard@demo.test', name: 'Guard' };
let orderSeq = 0;
const oid = () => `guard-order-${++orderSeq}`;

function login(user: { id: string; email: string; name: string } | null = USER) {
    (globalThis as Record<string, unknown>).__MANUAL_DEMO_GUARD_USER__ = user;
}

const NOW = Date.now();

function buyAccion(over: Record<string, unknown> = {}) {
    return {
        instrument: { kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA' },
        side: 'buy',
        quantity: 10,
        price: 10,
        currency: 'EUR',
        fee: 0,
        executedAt: NOW - 60_000,
        clientOrderId: oid(),
        ...over,
    };
}

beforeEach(() => {
    modelStub.__reset();
    orderSeq = 0;
    login();
});

describe('auth y validación de entrada', () => {
    it('sin sesión devuelve error y NO toca la base de datos', async () => {
        login(null);
        const r = await actions.placeManualOrder(buyAccion());
        assert.equal(r.ok, false);
        if (!r.ok) assert.match(r.message, /Inicia sesión/);
        assert.deepEqual(modelStub.__counts(), { accounts: 0, trades: 0 });
    });

    it('entrada malformada: campo señalado y nada grabado', async () => {
        const cases: Array<[Record<string, unknown>, string]> = [
            [buyAccion({ quantity: 1.5 }), 'quantity'],
            [buyAccion({ quantity: 0 }), 'quantity'],
            [buyAccion({ price: -3 }), 'price'],
            [buyAccion({ price: 1.23456 }), 'price'],
            [buyAccion({ clientOrderId: 'x' }), 'clientOrderId'],
            [buyAccion({ executedAt: 1_760_000_000 }), 'executedAt'], // segundos, no ms
            [buyAccion({ executedAt: NOW + 3_600_000 }), 'executedAt'], // futuro
            [buyAccion({ currency: 'GBP' }), 'currency'],
            [buyAccion({ instrument: { kind: 'accion', symbol: '<script>' } }), 'symbol'],
        ];
        for (const [input, field] of cases) {
            const r = await actions.placeManualOrder(input);
            assert.equal(r.ok, false, JSON.stringify(input));
            if (!r.ok) assert.equal(r.field, field, JSON.stringify(input));
        }
        assert.deepEqual(modelStub.__counts(), { accounts: 0, trades: 0 });
    });
});

describe('órdenes de acciones con dinero ficticio multidivisa', () => {
    it('compra EUR válida: filled, cash 100.000 - 100 y posición 10', async () => {
        const r = await actions.placeManualOrder(buyAccion());
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 99_900);
            assert.equal(r.state.positions.length, 1);
            assert.equal(r.state.positions[0].quantity, 10);
            assert.ok(r.state.notices.some((n) => n.includes('manual simulado')));
        }
    });

    it('idempotencia: mismo clientOrderId devuelve duplicate sin duplicar el fill', async () => {
        const order = buyAccion({ clientOrderId: oid() });
        await actions.placeManualOrder(order);
        const r = await actions.placeManualOrder(order);
        assert.ok(r.ok);
        if (r.ok) assert.equal(r.outcome, 'duplicate');
        assert.equal(modelStub.__counts().trades, 1);
        const acc = await actions.getManualDemoAccount();
        assert.ok(acc.ok);
        if (acc.ok) assert.equal(acc.state.cashEUR, 99_900);
    });

    it('compra en USD sin saldo: rechazo TOTAL grabado en el historial, cash intacto', async () => {
        const r = await actions.placeManualOrder(buyAccion({ currency: 'USD' }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /insuficiente/);
            assert.equal(r.state.cashUSD, 0);
            assert.equal(r.state.cashEUR, 100_000);
        }
        const hist = await actions.getManualDemoOrders();
        assert.ok(hist.ok);
        if (hist.ok) {
            assert.equal(hist.orders.length, 1);
            assert.equal(hist.orders[0].status, 'rejected');
            assert.equal(hist.orders[0].fillPrice, null);
        }

    });

    it('sobreventa: rechazo total, ni cash ni posición cambian; venta correcta después sí', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 2, price: 10 }));
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 20 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /posición/);
            assert.equal(r.state.cashEUR, 99_980); // solo la compra de 2x10
            assert.equal(r.state.positions[0].quantity, 2);
        }
        const ok = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 2, price: 20 });
        assert.ok(ok.ok);
        if (ok.ok) {
            assert.equal(ok.outcome, 'filled');
            assert.equal(ok.state.cashEUR, 100_020);
            assert.equal(ok.state.positions.length, 0);
            assert.equal(ok.state.realizedEUR, 20);
        }
    });
});

describe('conversión manual simulada EUR<->USD', () => {
    const fx = (over: Record<string, unknown> = {}) => ({
        from: 'EUR',
        to: 'USD',
        amount: 2_000,
        rate: 1.2,
        executedAt: NOW - 60_000,
        clientOrderId: oid(),
        ...over,
    });

    it('conversión válida: abona USD, resta EUR y queda etiquetada', async () => {
        const r = await actions.convertManualDemoCurrency(fx());
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 98_000);
            assert.equal(r.state.cashUSD, 2_400);
        }
    });

    it('from === to se rechaza (crearía dinero); importe de 50,50 EUR con decimales sí vale', async () => {
        const same = await actions.convertManualDemoCurrency(fx({ to: 'EUR' }));
        assert.equal(same.ok, false);
        if (!same.ok) assert.equal(same.field, 'to');
        const cents = await actions.convertManualDemoCurrency(fx({ amount: 50.5, rate: 1.1 }));
        assert.ok(cents.ok);
        if (cents.ok) {
            assert.equal(cents.outcome, 'filled');
            assert.equal(cents.state.cashEUR, 99_949.5);
            assert.ok(Math.abs(cents.state.cashUSD - 55.55) < 1e-9);
        }
    });

    it('sin conversión previa, la compra en USD se rechaza; tras convertir, funciona y descuenta prima+fee', async () => {
        const denied = await actions.placeManualOrder(buyAccion({ currency: 'USD', instrument: { kind: 'accion', symbol: 'ASTS', name: 'AST SpaceMobile' } }));
        assert.ok(denied.ok);
        if (denied.ok) assert.equal(denied.outcome, 'rejected');
        await actions.convertManualDemoCurrency(fx());
        const r = await actions.placeManualOrder(
            buyAccion({ instrument: { kind: 'accion', symbol: 'ASTS', name: 'AST SpaceMobile' }, quantity: 10, price: 40, currency: 'USD', fee: 5 }),
        );
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashUSD, 2_400 - 405);
            assert.equal(r.state.positions[0].quantity, 10);
        }
    });

    it('la posición en EUR no cubre una venta en USD del mismo símbolo', async () => {
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'SAN.MC', name: 'Santander' } }));
        const r = await actions.placeManualOrder({ ...buyAccion(), instrument: { kind: 'accion', symbol: 'SAN.MC', name: 'Santander' }, side: 'sell', quantity: 1, price: 10, currency: 'USD' });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.equal(r.state.cashUSD, 0);
        }
    });
});

describe('opciones (buildOptionFill real, saldo y posición derivados en la transacción)', () => {
    const call = {
        underlying: 'ASTS',
        callPut: 'call',
        strike: 30,
        expiry: '2027-01-15',
        multiplier: 100,
        deliverable: 'acciones',
        adjusted: false,
    };
    const opt = (over: Record<string, unknown> = {}) => ({
        instrument: { kind: 'opcion', contract: call },
        side: 'buy',
        openClose: 'open',
        quantity: 2,
        price: 1.5,
        currency: 'USD',
        fee: 0,
        executedAt: NOW - 60_000,
        clientOrderId: oid(),
        ...over,
    });
    const withUsd = async () => {
        await actions.convertManualDemoCurrency({ from: 'EUR', to: 'USD', amount: 10_000, rate: 1.2, executedAt: NOW - 120_000, clientOrderId: oid() });
    };

    it('buy-to-open: 2 contratos call a prima 1,5 cuestan 300 USD (prima x 100)', async () => {
        await withUsd();
        const r = await actions.placeManualOrder(opt());
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashUSD, 12_000 - 300);
            assert.equal(r.state.positions[0].kind, 'opcion');
            assert.equal(r.state.positions[0].quantity, 2);
        }
    });

    it('sell-to-open se rechaza en fase 1; prima con 5 decimales se rechaza; contrato vencido se rechaza', async () => {
        await withUsd();
        const short = await actions.placeManualOrder(opt({ side: 'sell', openClose: 'open' }));
        assert.ok(short.ok);
        if (short.ok) assert.match(short.reason ?? '', /Fase 1/);
        const dec = await actions.placeManualOrder(opt({ price: 1.23456 }));
        assert.equal(dec.ok, false);
        if (!dec.ok) assert.equal(dec.field, 'price');
        const expired = await actions.placeManualOrder(opt({ instrument: { kind: 'opcion', contract: { ...call, expiry: '2020-01-17' } } }));
        assert.ok(expired.ok);
        if (expired.ok) assert.match(expired.reason ?? '', /vencio/);
    });

    it('sell-to-close por encima de lo abierto se rechaza entero; cerrar lo abierto sí funciona', async () => {
        await withUsd();
        await actions.placeManualOrder(opt());
        const tooMany = await actions.placeManualOrder(opt({ side: 'sell', openClose: 'close', quantity: 3 }));
        assert.ok(tooMany.ok);
        if (tooMany.ok) assert.match(tooMany.reason ?? '', /abiertos/);
        const close = await actions.placeManualOrder(opt({ side: 'sell', openClose: 'close', quantity: 2, price: 2 }));
        assert.ok(close.ok);
        if (close.ok) {
            assert.equal(close.outcome, 'filled');
            assert.equal(close.state.cashUSD, 12_000 - 300 + 400);
            assert.equal(close.state.realizedUSD, 100);
        }
    });
});

describe('concurrencia y aislamiento', () => {
    it('conflicto de versión: reintenta y completa; conflicto permanente: error honesto sin grabar', async () => {
        modelStub.__failNextVersionUpdates(1);
        const r = await actions.placeManualOrder(buyAccion());
        assert.ok(r.ok);
        if (r.ok) assert.equal(r.outcome, 'filled');
        modelStub.__failNextVersionUpdates(10);
        const stuck = await actions.placeManualOrder(buyAccion());
        assert.equal(stuck.ok, false);
        if (!stuck.ok) assert.match(stuck.message, /otra orden/);
    });

    it('dos usuarios no comparten libro ni saldos', async () => {
        await actions.placeManualOrder(buyAccion());
        login({ id: 'guard-user-2', email: 'b@demo.test', name: 'Other' });
        const acc = await actions.getManualDemoAccount();
        assert.ok(acc.ok);
        if (acc.ok) {
            assert.equal(acc.state.cashEUR, 100_000);
            assert.equal(acc.state.positions.length, 0);
        }
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 1, price: 10 });
        assert.ok(r.ok);
        if (r.ok) assert.equal(r.outcome, 'rejected');
        login(USER);
        const mine = await actions.getManualDemoOrders();
        assert.ok(mine.ok);
        if (mine.ok) assert.equal(mine.orders.length, 1);
    });

    it('si el despliegue no soporta transacciones: error honesto y nada degradado', async () => {
        connStub.__setStartSessionError(new Error('Transaction numbers are only allowed on a replica set member'));
        const r = await actions.placeManualOrder(buyAccion());
        assert.equal(r.ok, false);
        if (!r.ok) assert.match(r.message, /transacciones/);
        assert.equal(modelStub.__counts().trades, 0);
    });
});
