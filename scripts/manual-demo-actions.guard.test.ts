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
    __snapshot(): { accounts: Array<Record<string, unknown>>; trades: Array<Record<string, unknown>> };
    __seedTrade(doc: Record<string, unknown>): Record<string, unknown>;
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
