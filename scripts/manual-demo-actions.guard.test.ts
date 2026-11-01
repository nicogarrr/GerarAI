/**
 * Guard de las server actions de la cuenta demo manual
 * (lib/actions/manual-demo.actions.ts): auth, validación, idempotencia,
 * concurrencia por versión, multidivisa y opciones, ejecutando el código
 * REAL de las actions sobre modelos en memoria (loader co-ubicado).
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-actions.guard.test.ts
 */
import { afterEach, beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./manual-demo-guard.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
const actions = await import('../lib/actions/manual-demo.actions.ts');
const modelStub = (await import('@/database/models/manual-demo.model')) as unknown as {
    __reset(): void;
    __failNextVersionUpdates(n: number): void;
    __counts(): { accounts: number; trades: number };
    __snapshot(): { accounts: Array<Record<string, unknown>>; trades: Array<Record<string, unknown>> };
    __seedTrade(doc: Record<string, unknown>): Record<string, unknown>;
    __dupNextTradeCreate(row: Record<string, unknown>): void;
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

    it('venta con comisión que supera el efectivo tras la venta: rechazada (sin sobregiro), libro intacto', async () => {
        // cash 100.000 -> compra 1x99.990 fee 10 = cash 0 -> venta @10 fee 50: 0+10-50 = -40
        await actions.placeManualOrder(buyAccion({ quantity: 1, price: 99_990, fee: 10 }));
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 1, price: 10, fee: 50 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /sobregiro/);
            assert.equal(r.state.cashEUR, 0);
            assert.equal(r.state.positions[0].quantity, 1);
        }
    });

    it('venta con comisión exactamente igual al efectivo tras la venta: aceptada (frontera)', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 1, price: 99_990, fee: 10 }));
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 1, price: 10, fee: 10 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 0);
            assert.equal(r.state.positions.length, 0);
        }
    });

    it('rechazo por sobregiro de comisión es idempotente (mismo clientOrderId, un solo rejected)', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 1, price: 99_990, fee: 10 }));
        const dupId = 'guard-fee-dup-0001';
        const order = { ...buyAccion(), side: 'sell', quantity: 1, price: 10, fee: 50, clientOrderId: dupId };
        const r1 = await actions.placeManualOrder(order);
        const r2 = await actions.placeManualOrder(order);
        assert.ok(r1.ok && r2.ok);
        if (r1.ok && r2.ok) {
            assert.equal(r1.outcome, 'rejected');
            assert.equal(r2.outcome, 'duplicate');
            assert.equal(r2.reason, r1.reason);
        }
        const history = await actions.getManualDemoOrders();
        assert.ok(history.ok);
        if (history.ok) {
            const rows = history.orders.filter((o: { clientOrderId: string }) => o.clientOrderId === dupId);
            assert.equal(rows.length, 1);
            assert.equal(rows[0].status, 'rejected');
        }
    });

    const optionOrder = (over: Record<string, unknown> = {}) => ({
        instrument: { kind: 'opcion', contract: { underlying: 'ASTS', expiry: '2027-01-15', strike: 50, callPut: 'call', multiplier: 100, deliverable: 'acciones', adjusted: false } },
        side: 'buy',
        openClose: 'open',
        quantity: 1,
        price: 1,
        currency: 'EUR',
        fee: 0,
        executedAt: NOW - 50_000,
        clientOrderId: oid(),
        ...over,
    });

    it('cierre de opción con comisión exactamente igual al efectivo tras la prima: aceptado (frontera)', async () => {
        await actions.placeManualOrder(optionOrder()); // cash 100.000 -> 99.900
        const r = await actions.placeManualOrder(optionOrder({ side: 'sell', openClose: 'close', fee: 100_000 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled'); // 99.900 + 100 - 100.000 = 0
            assert.equal(r.state.cashEUR, 0);
            assert.equal(r.state.positions.length, 0);
        }
    });

    it('cierre de opción con comisión que supera el efectivo tras la prima: rechazado (sin sobregiro), libro intacto', async () => {
        await actions.placeManualOrder(optionOrder()); // cash 100.000 -> 99.900
        const r = await actions.placeManualOrder(optionOrder({ side: 'sell', openClose: 'close', fee: 100_000.01 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected'); // 99.900 + 100 - 100.000,01 < 0
            assert.match(r.reason ?? '', /sobregiro/);
            assert.equal(r.state.cashEUR, 99_900);
            assert.equal(r.state.positions[0].quantity, 1);
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
        if (expired.ok) assert.match(expired.reason ?? '', /venci[óo]/);
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

describe('R3: coherencia temporal (el libro se recalcula por executedAt, no por orden de alta)', () => {
    const T0 = NOW - 300_000;
    const T1 = NOW - 200_000;
    const T2 = NOW - 100_000;

    it('compra USD antedatada ANTES de la conversión que la financia: rechazada, nada grabado como fill', async () => {
        await actions.convertManualDemoCurrency({ from: 'EUR', to: 'USD', amount: 1000, rate: 1.2, executedAt: T2, clientOrderId: oid() });
        const r = await actions.placeManualOrder(
            buyAccion({ instrument: { kind: 'accion', symbol: 'ASTS', name: 'ASTS' }, quantity: 10, price: 40, currency: 'USD', executedAt: T1 }),
        );
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /fecha de ejecución/);
            assert.equal(r.state.cashUSD, 1_200);
            assert.equal(r.state.positions.length, 0);
        }
    });

    it('venta antedatada ANTES de su compra: rechazada', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 10, price: 10, executedAt: T2 }));
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 12, executedAt: T1 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.equal(r.state.positions[0]?.quantity, 10);
        }
    });

    it('compra antedatada que gasta el efectivo que una compra POSTERIOR ya gastó: rechazada por descuadrar la posterior', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 9000, price: 10, executedAt: T2 })); // 90.000 EUR en T2
        const r = await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'IBE.MC', name: 'Iberdrola' }, quantity: 5000, price: 10, executedAt: T1 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            // La compra posterior existente sigue intacta.
            assert.equal(r.state.positions.length, 1);
            assert.equal(r.state.cashEUR, 10_000);
        }
    });

    it('venta antedatada que consumiría lotes que una venta POSTERIOR ya cerró: rechazada', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 10, price: 10, executedAt: T0 }));
        await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 10, price: 12, executedAt: T2 });
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 4, price: 11, executedAt: T1 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.equal(r.state.positions.length, 0);
            assert.equal(r.state.realizedEUR, 20);
        }
    });

    it('antedatación COHERENTE (no descuadra nada): aceptada y el libro posterior sigue válido', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 10, price: 10, executedAt: T2 }));
        const r = await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'ITX.MC', name: 'Inditex' }, quantity: 5, price: 20, executedAt: T1 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 100_000 - 100 - 100);
            assert.equal(r.state.positions.length, 2);
            assert.deepEqual(r.state.violations, []);
        }
        // Y una venta posterior de la posición antedatada funciona con FIFO correcto.
        const sell = await actions.placeManualOrder({ ...buyAccion(), instrument: { kind: 'accion', symbol: 'ITX.MC', name: 'Inditex' }, side: 'sell', quantity: 5, price: 25, executedAt: NOW - 1_000 });
        assert.ok(sell.ok);
        if (sell.ok) {
            assert.equal(sell.outcome, 'filled');
            assert.equal(sell.state.realizedEUR, 25);
        }
    });
});

describe('R3b: rediseño insertar→releer→abortar (orden persistido real)', () => {
    const T0 = NOW - 300_000;
    const T1 = NOW - 200_000;
    const T2 = NOW - 100_000;

    function seedTrade(over: Record<string, unknown> = {}) {
        const id = oid();
        return modelStub.__seedTrade({
            userId: USER.id,
            clientOrderId: id,
            kind: 'accion',
            symbol: 'BBVA.MC',
            name: 'BBVA',
            contract: null,
            side: 'buy',
            openClose: 'open',
            fxFrom: null,
            fxTo: null,
            quantity: 10,
            status: 'filled',
            fillPrice: 10,
            currency: 'EUR',
            fee: 0,
            fillSource: 'manual-simulado',
            executedAt: new Date(T1),
            rejectReason: null,
            _id: `seed-${id}`,
            createdAt: new Date(T1),
            ...over,
        });
    }

    it('rechazo por divergencia: rollback SIN fill y caché/versión intactos; rechazo grabado aparte', async () => {
        const buy = await actions.placeManualOrder(buyAccion({ quantity: 10, price: 10, executedAt: T2 }));
        assert.ok(buy.ok);
        if (buy.ok) assert.equal(buy.outcome, 'filled');
        const before = modelStub.__snapshot().accounts[0];
        assert.equal(before.version, 1);
        assert.equal(before.cashEUR, 100_000 - 100);

        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 12, executedAt: T1 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /fecha de ejecución/);
        }
        // Sin fill ni escritura parcial: la cuenta cacheada no se movió.
        const after = modelStub.__snapshot().accounts[0];
        assert.equal(after.version, 1);
        assert.equal(after.cashEUR, 100_000 - 100);
        // 1 fill + 1 rechazo grabado en escritura separada.
        assert.equal(modelStub.__counts().trades, 2);
        const rows = modelStub.__snapshot().trades;
        assert.equal(rows.filter((t) => t.status === 'filled').length, 1);
        assert.equal(rows.filter((t) => t.status === 'rejected').length, 1);
    });

    it('empate exacto (executedAt, createdAt): desempate por _id determinista sin importar el orden de inserción', async () => {
        const run = async (pushSellFirst: boolean) => {
            modelStub.__reset();
            const created = new Date(T1);
            const sell = { side: 'sell', quantity: 10, fillPrice: 12, _id: 'seed-aa', createdAt: created, executedAt: new Date(T1) };
            const buy = { side: 'buy', quantity: 10, fillPrice: 10, _id: 'seed-zz', createdAt: created, executedAt: new Date(T1) };
            if (pushSellFirst) { seedTrade(sell); seedTrade(buy); } else { seedTrade(buy); seedTrade(sell); }
            // _id aa < zz: la venta se ordena ANTES, se total-rechaza por falta de
            // posición y la compra queda (posición 10). Una venta posterior de 5
            // solo cuadra con ese orden.
            const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 12, executedAt: NOW - 1_000 });
            assert.ok(r.ok);
            if (r.ok) {
                assert.equal(r.outcome, 'filled');
                assert.equal(r.state.positions[0]?.quantity, 5);
            }
        };
        await run(true);
        await run(false);
    });

    it('createdAt futuro en un doc existente: la nueva op se ordena antes y se rechaza sin fill (rollback real)', async () => {
        // FX EUR→USD persistida con createdAt FUTURO (dato anómalo preexistente).
        modelStub.__seedTrade({
            userId: USER.id,
            clientOrderId: oid(),
            kind: 'fx',
            symbol: 'EURUSD',
            name: 'Conversión manual EUR→USD',
            contract: null,
            side: 'buy',
            openClose: 'open',
            fxFrom: 'EUR',
            fxTo: 'USD',
            quantity: 1000,
            status: 'filled',
            fillPrice: 1.2,
            currency: 'EUR',
            fee: 0,
            fillSource: 'manual-simulado',
            executedAt: new Date(T2),
            rejectReason: null,
            _id: 'seed-fx-futura',
            createdAt: new Date(NOW + 3_600_000),
        });
        const r = await actions.placeManualOrder(
            buyAccion({ instrument: { kind: 'accion', symbol: 'ASTS', name: 'ASTS' }, quantity: 10, price: 40, currency: 'USD', executedAt: T2 }),
        );
        assert.ok(r.ok);
        if (r.ok) {
            // Mismo executedAt, createdAt menor → la compra se ordena ANTES de
            // la FX que la financia: violación nueva → divergencia → rechazo.
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /fecha de ejecución/);
            assert.equal(r.state.cashUSD, 1_200);
        }
        // Solo queda la semilla: el fill se deshizo con la transacción.
        assert.equal(modelStub.__counts().trades, 2); // semilla + rechazo grabado aparte
        assert.equal(modelStub.__snapshot().trades.filter((t) => t.status === 'filled').length, 1);
        // Sin bump de versión (nunca hubo fill confirmado).
        assert.equal(modelStub.__snapshot().accounts[0].version, 0);
    });

    it('carrera mismo clientOrderId con payload distinto: conflicto explícito (H17), no duplicado silencioso', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 10, price: 10, executedAt: T2 }));
        const raceId = 'race-reason-1';
        // El ganador de la carrera ya grabó una fila con OTRO payload.
        modelStub.__dupNextTradeCreate({
            userId: USER.id, clientOrderId: raceId, kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
            contract: null, side: 'sell', openClose: 'open', fxFrom: null, fxTo: null, quantity: 3,
            status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0, fillSource: 'manual-simulado',
            executedAt: null, rejectReason: 'REASON-PERSISTIDO-DEL-GANADOR',
        });
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 12, executedAt: T1, clientOrderId: raceId });
        // El idempotency-key pertenece a UN payload: reusarlo con otra
        // operación es un error explícito (campo clientOrderId), nunca el
        // resultado viejo devuelto como si esta orden hubiera corrido.
        assert.ok(!r.ok);
        if (!r.ok) {
            assert.equal(r.field, 'clientOrderId');
            assert.match(r.message, /ya se usó con una operación distinta/);
        }
        // Solo el buy y la fila del ganador: este intento no grabó nada.
        assert.equal(modelStub.__counts().trades, 2);
    });

    it('venta antedatada con comisión que sobregira el cash EN SU FECHA: rechazada por el replay, libro y caché intactos', async () => {
        // T0 compra 20@10 (cash 99.800) → T2 venta 10@5000 (cash 149.800).
        // La venta antedatada en T1 con fee 150.000 cabe contra el cash ACTUAL
        // (149.800+1.000) pero NO en su fecha (99.800+1.000-150.000 = -49.200):
        // antes del fix de accounting.ts el replay la aplicaba sin violation.
        await actions.placeManualOrder(buyAccion({ quantity: 20, price: 10, executedAt: T0 }));
        await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 10, price: 5000, executedAt: T2 });
        const r = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 10, price: 100, fee: 150_000, executedAt: T1 });
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /comisión/);
            assert.equal(r.state.cashEUR, 149_800);
            assert.equal(r.state.positions[0]?.quantity, 10);
        }
        // 2 fills + 1 fila de rechazo; versión solo de los fills confirmados.
        assert.equal(modelStub.__counts().trades, 3);
        assert.equal(modelStub.__snapshot().trades.filter((t) => t.status === 'rejected').length, 1);
        assert.equal(modelStub.__snapshot().accounts[0].version, 2);
        assert.equal(modelStub.__snapshot().accounts[0].cashEUR, 149_800);
    });

    it('reintento con el mismo clientOrderId tras rechazo por divergencia: duplicate sin segunda fila', async () => {
        await actions.placeManualOrder(buyAccion({ quantity: 10, price: 10, executedAt: T2 }));
        const retryId = 'retry-divergence-1';
        const first = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 12, executedAt: T1, clientOrderId: retryId });
        assert.ok(first.ok);
        if (first.ok) assert.equal(first.outcome, 'rejected');
        const second = await actions.placeManualOrder({ ...buyAccion(), side: 'sell', quantity: 5, price: 12, executedAt: T1, clientOrderId: retryId });
        assert.ok(second.ok);
        if (second.ok) {
            assert.equal(second.outcome, 'duplicate');
            assert.match(second.reason ?? '', /fecha de ejecución/);
        }
        // buy + 1 única fila de rechazo.
        assert.equal(modelStub.__counts().trades, 2);
    });
});

type VRow = { status: string; note: string; marketValue: number | null; currencyBasis: string | null };
type VResult = { ok: boolean; valuation: { rows: VRow[]; coverage: { valued: number; total: number } }; listingUnavailable?: boolean; quoteFetchFailed?: boolean; retryAfterSeconds?: number | null };

describe('valoración bajo demanda (getManualDemoValuation)', () => {
    const g = globalThis as Record<string, unknown>;
    const realFetch = globalThis.fetch;
    // Payload crudo de Finnhub /quote (el modulo lo sanea y valida frescura por t).
    const finnhub = (c: number, over: Record<string, unknown> = {}) => ({ c, d: 0, dp: 0, h: c, l: c, o: c, pc: c, t: Math.floor(Date.now() / 1000), ...over });
    let listing: Array<{ symbol: string; currency: string }> | 'fail';
    let listingCalls = 0;
    let urls: string[] = [];
    const realNow = Date.now;
    let skewMs = 0;
    beforeEach(() => {
        // El listado de Finnhub se cachea 6 h en memoria del módulo: cada test avanza
        // el reloj 7 h para partir sin caché (y los fills se firman con el reloj real).
        skewMs += 7 * 3_600_000;
        Date.now = () => realNow() + skewMs;
        g.__GUARD_QUOTES__ = {};
        g.__GUARD_QUOTE_CALLS__ = [];
        urls = [];
        listingCalls = 0;
        listing = [{ symbol: 'BBVA', currency: 'USD' }, { symbol: 'T00', currency: 'USD' }];
        process.env.FINNHUB_API_KEY = 'guard-key';
        globalThis.fetch = (async (input: RequestInfo | URL) => {
            const url = String(input);
            urls.push(url);
            if (url.includes('/stock/symbol')) {
                listingCalls++;
                if (listing === 'fail') return new Response('no', { status: 500 });
                return new Response(JSON.stringify(listing), { status: 200 });
            }
            if (url.includes('/quote?')) {
                const symbol = decodeURIComponent(new URL(url).searchParams.get('symbol') ?? '');
                g.__GUARD_QUOTE_CALLS__ = (g.__GUARD_QUOTE_CALLS__ as string[]).concat(symbol);
                const q = (g.__GUARD_QUOTES__ as Record<string, unknown>)[symbol];
                if (q instanceof Error) throw q;
                if (q instanceof Response) return q;
                if (!q) return new Response(JSON.stringify({ c: 0, pc: 0, t: 0 }), { status: 200 });
                return new Response(JSON.stringify(q), { status: 200 });
            }
            throw new Error(`fetch inesperado en el guard: ${url}`);
        }) as typeof fetch;
    });
    afterEach(() => {
        Date.now = realNow;
        globalThis.fetch = realFetch;
        delete process.env.FINNHUB_API_KEY;
    });

    it('sin sesión devuelve error y no consulta cotizaciones ni base de datos', async () => {
        login(null);
        const r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.ok, false);
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, []);
        assert.deepEqual(modelStub.__counts(), { accounts: 0, trades: 0 });
    });

    it('es de solo lectura: con libro vacío NO crea la cuenta', async () => {
        const r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.ok, true);
        assert.deepEqual(r.valuation.coverage, { valued: 0, total: 0 });
        assert.equal(r.listingUnavailable, false, 'sin símbolos no hay listado que fallar');
        assert.deepEqual(modelStub.__counts(), { accounts: 0, trades: 0 });
    });

    it('Finnhub + divisa verificada en el listado: valora; libro intacto', async () => {
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'EUR', quantity: 10, price: 10 }));
        const before = JSON.stringify(modelStub.__snapshot());
        // La posición está en EUR y el listado dice USD: no coincide => N/D (sin conversión).
        g.__GUARD_QUOTES__ = { BBVA: finnhub(12) };
        const r1 = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r1.valuation.rows[0].status, 'divisa-no-coincide');
        assert.equal(JSON.stringify(modelStub.__snapshot()), before);
    });

    it('listado caído => N/D sin pedir cotizaciones; el fallo no se cachea y se reintenta', async () => {
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'EUR', quantity: 10, price: 10 }));
        g.__GUARD_QUOTES__ = { BBVA: finnhub(12) };
        listing = 'fail';
        let r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.listingUnavailable, true, 'listado caído con símbolos: señal estructurada para el backoff del cliente');
        assert.equal(r.valuation.rows[0].status, 'divisa-no-coincide');
        assert.equal(r.valuation.rows[0].note, 'No se pudo verificar la divisa de la cotización.');
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, [], 'sin divisa verificable no se pide la cotización');
        assert.equal(listingCalls, 1);
        listing = [{ symbol: 'BBVA', currency: 'EUR' }];
        r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.listingUnavailable, false, 'listado recuperado: no es fallo transitorio');
        assert.equal(r.valuation.rows[0].status, 'valorada', 'el fallo no se cacheó: reintenta y valora');
        assert.equal(listingCalls, 2);
        r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(listingCalls, 2, 'un listado correcto se reutiliza');
    });

    it('Finnhub sin dato (falla o precio viejo): N/D y NINGUNA llamada a Yahoo ni al backend', async () => {
        await actions.placeManualOrder(buyAccion());
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'OLD', name: 'Viejo' } }));
        listing = [{ symbol: 'BBVA.MC', currency: 'EUR' }, { symbol: 'OLD', currency: 'USD' }];
        g.__GUARD_QUOTES__ = { 'BBVA.MC': new Error('finnhub caido'), OLD: finnhub(5, { t: 1_000_000_000 }) };
        process.env.FMP_BACKEND_URL = 'http://backend.invalid';
        const r = (await actions.getManualDemoValuation()) as unknown as VResult;
        delete process.env.FMP_BACKEND_URL;
        assert.deepEqual(r.valuation.rows.map((x) => x.status), ['sin-cotizacion', 'sin-cotizacion']);
        assert.equal(r.valuation.rows[0].note, 'Sin cotización disponible de las fuentes admitidas (no se usa el precio de tus operaciones).');
        assert.ok(urls.every((u) => u.startsWith('https://finnhub.io/api/v1/')), urls.join(' | '));
        assert.ok(!urls.some((u) => /yahoo|backend|api\/market/.test(u)));
        assert.equal(listingCalls, 1);
    });

    it('proveedor caído en un símbolo: N/D en esa fila, sin romper la acción', async () => {
        await actions.placeManualOrder(buyAccion());
        listing = [{ symbol: 'BBVA.MC', currency: 'EUR' }];
        g.__GUARD_QUOTES__ = { 'BBVA.MC': new Error('proveedor caido') };
        const r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.ok, true);
        assert.equal(r.valuation.rows[0].status, 'sin-cotizacion');
    });

    it('USD verificado: acción en USD con cotización Finnhub se valora', async () => {
        await actions.convertManualDemoCurrency({ from: 'EUR', to: 'USD', amount: 1000, rate: 1.1, executedAt: NOW - 120_000, clientOrderId: oid() });
        const o = await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'USD', quantity: 10, price: 10 }));
        assert.equal(o.ok && o.outcome, 'filled');
        g.__GUARD_QUOTES__ = { BBVA: finnhub(12) };
        const r = (await actions.getManualDemoValuation()) as unknown as VResult;
        const row = r.valuation.rows[0];
        assert.equal(row.status, 'valorada');
        assert.equal(row.marketValue, 120);
        assert.equal(row.currencyBasis, 'finnhub-listado');
        assert.deepEqual(r.valuation.coverage, { valued: 1, total: 1 });
    });

    it('más de 25 símbolos: los sobrantes salen "No consultada" y solo se piden 25', async () => {
        for (let i = 0; i < 27; i++) {
            const r = await actions.placeManualOrder(
                buyAccion({ instrument: { kind: 'accion', symbol: `T${String(i).padStart(2, '0')}`, name: `T${i}` }, currency: 'EUR', quantity: 1, price: 1 }),
            );
            assert.equal(r.ok && r.outcome, 'filled');
        }
        g.__GUARD_QUOTE_CALLS__ = [];
        listing = Array.from({ length: 27 }, (_, i) => ({ symbol: `T${String(i).padStart(2, '0')}`, currency: 'EUR' }));
        const v = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(v.ok, true);
        assert.equal((g.__GUARD_QUOTE_CALLS__ as string[]).length, 25);
        assert.equal(listingCalls, 1, '25 símbolos => una sola descarga del listado');
        const rows = v.valuation.rows;
        assert.equal(rows.filter((x) => x.status === 'no-consultada').length, 2);
        assert.match(rows.find((x) => x.status === 'no-consultada')?.note ?? '', /límite de 25/);
    });

    it('llamadas concurrentes comparten una sola descarga del listado (inflight)', async () => {
        await actions.convertManualDemoCurrency({ from: 'EUR', to: 'USD', amount: 1000, rate: 1.1, executedAt: NOW - 120_000, clientOrderId: oid() });
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'USD', quantity: 1, price: 1 }));
        g.__GUARD_QUOTES__ = { BBVA: finnhub(2) };
        await Promise.all([actions.getManualDemoValuation(), actions.getManualDemoValuation(), actions.getManualDemoValuation()]);
        assert.equal(listingCalls, 1);
    });

    it('causas distintas: símbolo ausente del listado vs proveedor de cotización caído', async () => {
        await actions.placeManualOrder(buyAccion());
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'DOWN', name: 'Down' } }));
        listing = [{ symbol: 'DOWN', currency: 'EUR' }];
        g.__GUARD_QUOTES__ = { DOWN: new Error('proveedor caido') };
        const r = (await actions.getManualDemoValuation()) as unknown as VResult;
        const byNote = r.valuation.rows.map((x) => x.note);
        assert.ok(byNote.includes('No se pudo verificar la divisa de la cotización.'), 'ausente del listado');
        assert.ok(byNote.some((n) => n.startsWith('Sin cotización disponible')), 'proveedor caído con divisa verificada');
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['DOWN'], 'solo se pide la cotización con divisa verificable');
    });

    it('quoteFetchFailed: solo si TODAS las cotizaciones verificables fallan; Retry-After propagado', async () => {
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'EUR', quantity: 1, price: 1 }));
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'T00', name: 'T00' }, currency: 'EUR', quantity: 1, price: 1 }));
        listing = [{ symbol: 'BBVA', currency: 'EUR' }, { symbol: 'T00', currency: 'EUR' }];
        // Todas fallan (429 con Retry-After y red): señal + espera del proveedor.
        g.__GUARD_QUOTES__ = { BBVA: new Response('throttled', { status: 429, headers: { 'retry-after': '120' } }), T00: new Error('timeout') };
        let r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.quoteFetchFailed, true, 'todas las cotizaciones verificables fallaron');
        assert.equal(r.retryAfterSeconds, 120, 'Retry-After del proveedor propagado');
        assert.equal(r.valuation.coverage.valued, 0);
        // El quote-cache anota el fallo (Retry-After 120 s / backoff 1 s): hay
        // que dejar pasar esa ventana para que la siguiente fase re-consulte.
        skewMs += 130_000;
        // Dato genuinamente ausente o viejo (respuesta OK saneada a null): NO es fallo de fetch.
        g.__GUARD_QUOTES__ = { BBVA: finnhub(5, { t: 1_000_000_000 }) }; // vieja; T00 sin entrada => { c: 0 }
        r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.quoteFetchFailed, false, 'dato ausente/viejo no arma backoff');
        assert.equal(r.retryAfterSeconds, null);
        // Éxito parcial: una falla y otra valora => no es fallo total.
        g.__GUARD_QUOTES__ = { BBVA: finnhub(12), T00: new Error('cae uno') };
        r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.quoteFetchFailed, false, 'éxito parcial no es fallo total');
        assert.equal(r.valuation.coverage.valued, 1);
        // Sin símbolos verificables (listado OK sin esos símbolos): no hay fetch que fallar.
        listing = [];
        r = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r.quoteFetchFailed, false, 'sin verificables no aplica');
        assert.equal(r.listingUnavailable, false, 'el listado respondió');
    });

    it('ahorro medido: misma ventana => 1 fetch por símbolo, libro releído fresco y asOf honesto', async () => {
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'EUR', quantity: 10, price: 10 }));
        listing = [{ symbol: 'BBVA', currency: 'EUR' }];
        g.__GUARD_QUOTES__ = { BBVA: finnhub(10) };
        const r1 = (await actions.getManualDemoValuation()) as unknown as VResult & { asOf: number };
        assert.equal(r1.valuation.rows[0].marketValue, 100, '10 x 10 con la primera cotización');
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['BBVA'], 'primer fetch real a Finnhub');
        // Nuevo fill DENTRO de la ventana de 20 s: el precio se mueve a 20
        // pero la caché sirve el de hace <20 s; el libro NO se cachea.
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'EUR', quantity: 10, price: 10 }));
        g.__GUARD_QUOTES__ = { BBVA: finnhub(20) };
        const r2 = (await actions.getManualDemoValuation()) as unknown as VResult & { asOf: number };
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['BBVA'], 'ahorro medido: cero fetches nuevos dentro del TTL');
        assert.equal(r2.valuation.rows[0].marketValue, 200, '20 acciones x 10 (cotización cacheada): el fill nuevo SÍ se refleja');
        assert.equal(r2.asOf, r1.asOf, 'asOf = min(fetchedAt): la UI ve que el dato no es recién pedido');
        // Expirada la ventana se reconsulta y se usa el precio nuevo.
        skewMs += 21_000;
        const r3 = (await actions.getManualDemoValuation()) as unknown as VResult & { asOf: number };
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['BBVA', 'BBVA'], 'expirado el TTL vuelve a pedir');
        assert.equal(r3.valuation.rows[0].marketValue, 400, '20 acciones x 20 con la cotización fresca');
        assert.ok(r3.asOf > r1.asOf, 'asOf avanza con el fetch nuevo');
    });

    it('429 frena la siguiente valoración (backoff compartido, medido): cero fetches durante Retry-After', async () => {
        await actions.placeManualOrder(buyAccion({ instrument: { kind: 'accion', symbol: 'BBVA', name: 'BBVA' }, currency: 'EUR', quantity: 1, price: 1 }));
        listing = [{ symbol: 'BBVA', currency: 'EUR' }];
        g.__GUARD_QUOTES__ = { BBVA: new Response('throttled', { status: 429, headers: { 'retry-after': '120' } }) };
        const r1 = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.equal(r1.quoteFetchFailed, true);
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['BBVA']);
        // Re-valoración inmediata (p. ej. siguiente render): NO martillea al proveedor.
        g.__GUARD_QUOTES__ = { BBVA: finnhub(10) };
        const r2 = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['BBVA'], 'ahorro medido: Retry-After frena el reintento');
        assert.equal(r2.quoteFetchFailed, true);
        assert.equal(r2.retryAfterSeconds, 120, 'la espera restante se sigue propagando');
        // Cumplida la espera, reintenta y valora.
        skewMs += 121_000;
        const r3 = (await actions.getManualDemoValuation()) as unknown as VResult;
        assert.deepEqual(g.__GUARD_QUOTE_CALLS__, ['BBVA', 'BBVA'], 'cumplido Retry-After se reintenta');
        assert.equal(r3.valuation.rows[0].status, 'valorada');
    });
});

/* ------------------------------------------------------------------ */
/* Historial PAGINADO (getManualDemoHistory, en manual-demo.actions):  */
/* (createdAt, _id), autorización por página, empates, concurrencia.   */
/* ------------------------------------------------------------------ */

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
const historyActions = await import('../lib/actions/manual-demo.actions.ts');

type HistoryPage =
    | { ok: true; orders: Array<{ clientOrderId: string; status: string; fillPrice: number | null; rejectReason: string | null }>; hasMore: boolean; nextBefore: string | null }
    | { ok: false; message: string; field?: string };

/** Siembra `count` filas de historial: row-0 la más reciente (createdAt y _id
 * decrecen con i, así el orden esperado es simplemente row-0..row-(n-1)). */
function seedHistoryRows(userId: string, count: number, opts: { startMs?: number; stepMs?: number; tag?: string } = {}) {
    const start = opts.startMs ?? NOW - 3_600_000;
    const step = opts.stepMs ?? 1_000;
    const tag = opts.tag ?? 'hist';
    for (let i = 0; i < count; i++) {
        modelStub.__seedTrade({
            userId,
            clientOrderId: `${userId}-${tag}-${i}`,
            kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
            contract: null, side: 'buy', openClose: 'open',
            fxFrom: null, fxTo: null,
            quantity: 1, status: 'filled', fillPrice: 10,
            currency: 'EUR', fee: 0, fillSource: 'manual-simulado',
            executedAt: new Date(start - i * step),
            rejectReason: null,
            createdAt: new Date(start - i * step),
            updatedAt: new Date(start - i * step),
            _id: `${userId}-${tag}-row-${String(i).padStart(6, '0')}`,
        });
    }
}

const expectedIds = (userId: string, count: number, tag = 'hist') =>
    Array.from({ length: count }, (_, i) => `${userId}-${tag}-${i}`);

describe('historial paginado (cursor estable)', () => {
    it('recorre 250 filas sin perder ni repetir (páginas de 200 + 50)', async () => {
        seedHistoryRows(USER.id, 250);
        const p1 = (await historyActions.getManualDemoHistory()) as unknown as HistoryPage;
        assert.ok(p1.ok);
        assert.equal(p1.orders.length, 200, 'primera página: el defecto es 200');
        assert.equal(p1.hasMore, true);
        assert.ok(p1.nextBefore, 'hay cursor para la siguiente página');
        const p2 = (await historyActions.getManualDemoHistory({ before: p1.nextBefore })) as unknown as HistoryPage;
        assert.ok(p2.ok);
        assert.equal(p2.orders.length, 50);
        assert.equal(p2.hasMore, false);
        assert.equal(p2.nextBefore, null, 'última página: sin cursor');
        const all = [...p1.orders, ...p2.orders].map((r) => r.clientOrderId);
        assert.deepEqual(all, expectedIds(USER.id, 250), 'orden exacto, sin pérdidas ni duplicados');
    });

    it('autoriza por usuario en CADA página: ni fuga con cursor propio ni con cursor ajeno', async () => {
        const OTHER = 'guard-user-otro';
        seedHistoryRows(USER.id, 250);
        seedHistoryRows(OTHER, 10, { tag: 'ajena' });
        // Recorrido completo del usuario: solo filas suyas.
        let before: string | null = null;
        const seen: string[] = [];
        do {
            const p = (await historyActions.getManualDemoHistory(before ? { before } : undefined)) as unknown as HistoryPage;
            assert.ok(p.ok);
            seen.push(...p.orders.map((r) => r.clientOrderId));
            before = p.hasMore ? p.nextBefore : null;
        } while (before);
        assert.equal(seen.length, 250);
        assert.ok(seen.every((id) => id.startsWith(`${USER.id}-`)), 'ninguna fila ajena en todo el recorrido');
        // Cursor forjado apuntando a una fila AJENA: el filtro userId manda.
        const foreignBefore = `${NOW - 3_600_000 - 5 * 1_000}:${OTHER}-ajena-row-000005`;
        const p = (await historyActions.getManualDemoHistory({ before: foreignBefore })) as unknown as HistoryPage;
        assert.ok(p.ok, 'un cursor ajeno bien formado no rompe la consulta');
        assert.ok(p.orders.every((r) => r.clientOrderId.startsWith(`${USER.id}-`)), 'cero fuga con cursor ajeno');
    });

    it('rechaza cursores inválidos o manipulados (campo before)', async () => {
        seedHistoryRows(USER.id, 5);
        for (const bad of ['', 'abc', '123', '1:', '1:bad id!', `${NOW}:${'x'.repeat(100)}`, 'no-es-cursor:trd-1']) {
            const r = (await historyActions.getManualDemoHistory({ before: bad })) as unknown as HistoryPage;
            assert.equal(r.ok, false, `rechazado: ${JSON.stringify(bad)}`);
            if (!r.ok) assert.equal(r.field, 'before');
        }
        for (const bad of [123, {}, [], true] as unknown[]) {
            const r = (await historyActions.getManualDemoHistory({ before: bad })) as unknown as HistoryPage;
            assert.equal(r.ok, false, 'tipos no string también se rechazan');
        }
    });

    it('empates de createdAt: orden determinista por _id y recorrido exacto entre páginas', async () => {
        // 5 filas con el MISMO createdAt (empate total) + ids ordenables.
        const tieMs = NOW - 60_000;
        const tieIds = ['tie-a', 'tie-b', 'tie-c', 'tie-d', 'tie-e'];
        for (const id of tieIds) {
            modelStub.__seedTrade({
                userId: USER.id, clientOrderId: `${USER.id}-${id}`,
                kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
                contract: null, side: 'buy', openClose: 'open', fxFrom: null, fxTo: null,
                quantity: 1, status: 'filled', fillPrice: 10, currency: 'EUR', fee: 0,
                fillSource: 'manual-simulado', executedAt: new Date(tieMs), rejectReason: null,
                createdAt: new Date(tieMs), updatedAt: new Date(tieMs),
                _id: `${USER.id}-${id}`,
            });
        }
        // Orden esperado: _id descendente (tie-e, tie-d, tie-c, tie-b, tie-a).
        const p1 = (await historyActions.getManualDemoHistory({ limit: 2 })) as unknown as HistoryPage;
        assert.ok(p1.ok);
        assert.deepEqual(p1.orders.map((r) => r.clientOrderId), [`${USER.id}-tie-e`, `${USER.id}-tie-d`]);
        assert.equal(p1.hasMore, true);
        // El cursor parte el empate a mitad: ni pérdida ni duplicado.
        const ids: string[] = [...p1.orders.map((r) => r.clientOrderId)];
        let before: string | null = p1.nextBefore;
        while (before) {
            const p = (await historyActions.getManualDemoHistory({ before, limit: 2 })) as unknown as HistoryPage;
            assert.ok(p.ok);
            ids.push(...p.orders.map((r) => r.clientOrderId));
            before = p.hasMore ? p.nextBefore : null;
        }
        assert.deepEqual(ids, tieIds.map((t) => `${USER.id}-${t}`).reverse(), 'recorrido exacto sobre el empate');
    });

    it('filas nuevas entre páginas no desplazan el recorrido (sin offset)', async () => {
        seedHistoryRows(USER.id, 250);
        const p1 = (await historyActions.getManualDemoHistory()) as unknown as HistoryPage;
        assert.ok(p1.ok && p1.nextBefore);
        // Llegan 3 filas NUEVAS (más recientes) antes de pedir la página 2.
        seedHistoryRows(USER.id, 3, { startMs: NOW, stepMs: 100, tag: 'nueva' });
        const p2 = (await historyActions.getManualDemoHistory({ before: p1.nextBefore })) as unknown as HistoryPage;
        assert.ok(p2.ok);
        assert.deepEqual(
            p2.orders.map((r) => r.clientOrderId),
            expectedIds(USER.id, 250).slice(200),
            'la página 2 es exactamente la cola esperada, sin corrimientos',
        );
        // Y un refresh (página 1 otra vez) muestra las nuevas arriba.
        const fresh = (await historyActions.getManualDemoHistory()) as unknown as HistoryPage;
        assert.ok(fresh.ok);
        assert.deepEqual(
            fresh.orders.slice(0, 3).map((r) => r.clientOrderId),
            [`${USER.id}-nueva-0`, `${USER.id}-nueva-1`, `${USER.id}-nueva-2`],
            'las filas nuevas encabezan el refresh',
        );
    });

    it('límite: defecto 200, tope 500 y valores absurdos saneados', async () => {
        seedHistoryRows(USER.id, 600);
        const def = (await historyActions.getManualDemoHistory()) as unknown as HistoryPage;
        assert.ok(def.ok && def.orders.length === 200 && def.hasMore);
        const max = (await historyActions.getManualDemoHistory({ limit: 500 })) as unknown as HistoryPage;
        assert.ok(max.ok && max.orders.length === 500 && max.hasMore);
        const clamped = (await historyActions.getManualDemoHistory({ limit: 99999 })) as unknown as HistoryPage;
        assert.ok(clamped.ok && clamped.orders.length === 500, 'limit por encima del tope se acota a 500');
        const min = (await historyActions.getManualDemoHistory({ limit: 0 })) as unknown as HistoryPage;
        assert.ok(min.ok && min.orders.length === 1, 'limit 0 se acota a 1');
        const junk = (await historyActions.getManualDemoHistory({ limit: 'x' })) as unknown as HistoryPage;
        assert.ok(junk.ok && junk.orders.length === 200, 'limit no numérico vuelve al defecto');
    });

    it('los rechazos siguen visibles en el historial paginado', async () => {
        // 20000 x 10 EUR = 200.000 > 100.000 iniciales: rechazo por saldo (no
        // validación de entrada: la cantidad está dentro del rango admitido).
        const r = (await actions.placeManualOrder(buyAccion({ quantity: 20000, price: 10 }))) as unknown as { ok: boolean; outcome?: string };
        assert.ok(r.ok && r.outcome === 'rejected', 'la orden se rechaza por saldo');
        const p = (await historyActions.getManualDemoHistory()) as unknown as HistoryPage;
        assert.ok(p.ok);
        assert.equal(p.orders.length, 1);
        const row = p.orders[0];
        assert.equal(row.status, 'rejected');
        assert.equal(row.fillPrice, null);
        assert.ok(row.rejectReason, 'el motivo del rechazo viaja en la fila');
    });

    it('sin sesión: error claro y ninguna fila', async () => {
        login(null);
        const r = (await historyActions.getManualDemoHistory()) as unknown as HistoryPage;
        assert.equal(r.ok, false);
        if (!r.ok) assert.match(r.message, /Inicia sesión/);
    });
});
