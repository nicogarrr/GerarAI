/**
 * Guard de la huella de idempotencia (H17): un clientOrderId pertenece a UN
 * payload. Reusarlo con una operación DISTINTA (otro precio, lado, símbolo,
 * contrato, o cruzando fill<->FX) NO es un duplicado silencioso: es un error
 * explícito que no graba nada. El reintento legítimo (mismo id, mismo
 * payload) sigue devolviendo duplicate sin grabar otra orden.
 *
 * Rechazadas (fix-2): las filas nuevas persisten un snapshot normalizado del
 * payload pedido (requestPayload) y la comparación es completa. Las filas
 * LEGACY sin snapshot comparan solo el subconjunto persistido; ver
 * scripts/manual-demo-reject-payload-guard.test.ts.
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-duplicate-payload-guard.test.ts
 */
import { beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./manual-demo-guard.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
const actions = await import('../lib/actions/manual-demo.actions.ts');
const modelStub = (await import('@/database/models/manual-demo.model')) as unknown as {
    __reset(): void;
    __counts(): { accounts: number; trades: number };
    __dupNextTradeCreate(row: Record<string, unknown>): void;
};

const USER = { id: 'guard-dup-1', email: 'dup@demo.test', name: 'Dup' };
let orderSeq = 0;
const oid = () => `guard-dup-${String(++orderSeq).padStart(4, '0')}`;
const NOW = Date.now();

function accion(over: Record<string, unknown> = {}) {
    return {
        instrument: { kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA' },
        side: 'buy',
        quantity: 1,
        price: 10,
        currency: 'EUR',
        fee: 0,
        executedAt: NOW - 60_000,
        clientOrderId: oid(),
        ...over,
    };
}

const opcion = (over: Record<string, unknown> = {}) => ({
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

const fx = (over: Record<string, unknown> = {}) => ({
    from: 'EUR',
    to: 'USD',
    amount: 50,
    rate: 1.1,
    executedAt: NOW - 40_000,
    clientOrderId: oid(),
    ...over,
});

beforeEach(() => {
    modelStub.__reset();
    orderSeq = 0;
    (globalThis as Record<string, unknown>).__MANUAL_DEMO_GUARD_USER__ = USER;
});

describe('huella de idempotencia: un clientOrderId = un payload', () => {
    it('reintento legítimo (mismo id, mismo payload): duplicate, sin grabar otra orden', async () => {
        const orden = accion({ clientOrderId: 'dup-same-01' });
        const r1 = await actions.placeManualOrder(orden);
        assert.ok(r1.ok && r1.outcome === 'filled');
        const r2 = await actions.placeManualOrder(orden);
        assert.ok(r2.ok);
        if (r2.ok) {
            assert.equal(r2.outcome, 'duplicate');
            assert.equal(r2.reason, null);
        }
        assert.equal(modelStub.__counts().trades, 1);
        // Resultado idéntico al original: mismo estado devuelto.
        assert.ok(r1.ok && r2.ok);
        if (r1.ok && r2.ok) {
            assert.equal(r2.state.cashEUR, r1.state.cashEUR);
            assert.equal(r2.state.positions.length, r1.state.positions.length);
        }
    });

    it('normalización sin falsos conflictos: distinto nombre visible o formato numérico NO es otra operación', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'dup-alias-01' }));
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'dup-alias-01', instrument: { kind: 'accion', symbol: 'bbva.mc', name: 'Banco Bilbao (otro alias)' }, price: 10.0 }));
        assert.ok(r.ok);
        if (r.ok) assert.equal(r.outcome, 'duplicate');
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('carrera E11000 en recordRejection: ganador MISMO payload -> rejected con el motivo PERSISTIDO', async () => {
        await actions.placeManualOrder(accion({ quantity: 10, price: 10, executedAt: NOW - 50_000 })); // posición 10
        // El ganador de la carrera graba el rechazo de ESTA misma operación (mismo payload comparable).
        modelStub.__dupNextTradeCreate({
            userId: USER.id, clientOrderId: 'dup-race-01', kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
            contract: null, side: 'sell', openClose: 'close', fxFrom: null, fxTo: null,
            quantity: 5, status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0,
            fillSource: 'manual-simulado', executedAt: null, rejectReason: 'REASON-PERSISTIDO-DEL-GANADOR',
        });
        // Venta antedatada ANTES de la compra -> divergencia temporal -> recordRejection -> E11000.
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'dup-race-01', side: 'sell', quantity: 5, price: 12, executedAt: NOW - 60_000 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.equal(r.reason, 'REASON-PERSISTIDO-DEL-GANADOR');
        }
        assert.equal(modelStub.__counts().trades, 2); // compra + rechazo del ganador
    });

    it('carrera E11000 en recordRejection: ganador DISTINTO payload -> conflicto explícito, no reason ajeno', async () => {
        await actions.placeManualOrder(accion({ quantity: 10, price: 10, executedAt: NOW - 50_000 })); // posición 10
        modelStub.__dupNextTradeCreate({
            userId: USER.id, clientOrderId: 'dup-race-02', kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
            contract: null, side: 'sell', openClose: 'close', fxFrom: null, fxTo: null,
            quantity: 3, status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0,
            fillSource: 'manual-simulado', executedAt: null, rejectReason: 'REASON-PERSISTIDO-DEL-GANADOR',
        });
        // Mismo clientOrderId pero cantidad distinta (3 vs 5): conflicto, no duplicate ni reason ajeno.
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'dup-race-02', side: 'sell', quantity: 5, price: 12, executedAt: NOW - 60_000 }));
        assert.equal(r.ok, false);
        if (!r.ok) assert.match(r.message, /operación distinta/);
        assert.equal(modelStub.__counts().trades, 2); // compra + ganador; este intento no graba
    });

    it('mismo id con OTRO precio: error explícito, no duplicate silencioso; no graba nada', async () => {
        const r1 = await actions.placeManualOrder(accion({ clientOrderId: 'dup-price-01', price: 10 }));
        assert.ok(r1.ok && r1.outcome === 'filled');
        const r2 = await actions.placeManualOrder(accion({ clientOrderId: 'dup-price-01', price: 11 }));
        assert.equal(r2.ok, false);
        if (!r2.ok) {
            assert.match(r2.message, /identificador de orden ya se usó con una operación distinta/);
            assert.equal(r2.field, 'clientOrderId');
        }
        assert.equal(modelStub.__counts().trades, 1);
        const cuenta = await actions.getManualDemoAccount();
        assert.ok(cuenta.ok);
        if (cuenta.ok) assert.equal(cuenta.state.cashEUR, 99_990); // solo el fill original
    });

    it('mismo id con OTRO lado (sell) o símbolo: error explícito', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'dup-side-01' }));
        const r2 = await actions.placeManualOrder(accion({ clientOrderId: 'dup-side-01', side: 'sell' }));
        assert.equal(r2.ok, false);
        const r3 = await actions.placeManualOrder(accion({ clientOrderId: 'dup-side-01', instrument: { kind: 'accion', symbol: 'SAN.MC', name: 'SAN' } }));
        assert.equal(r3.ok, false);
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('rechazo persistido: mismo id y mismo payload sigue siendo duplicate con el motivo (U1 intacto)', async () => {
        const cara = accion({ clientOrderId: 'dup-rej-01', quantity: 100_000, price: 999_999 });
        const r1 = await actions.placeManualOrder(cara);
        assert.ok(r1.ok && r1.outcome === 'rejected');
        const r2 = await actions.placeManualOrder(cara);
        assert.ok(r2.ok);
        if (r2.ok) {
            assert.equal(r2.outcome, 'duplicate');
            assert.match(r2.reason ?? '', /insuficiente/);
        }
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('fix-2: la rechazada persiste snapshot; mismo id con OTRO precio es conflicto explícito', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'dup-rej-02', quantity: 100_000, price: 999_999 }));
        const r2 = await actions.placeManualOrder(accion({ clientOrderId: 'dup-rej-02', quantity: 100_000, price: 888_888 }));
        assert.equal(r2.ok, false);
        if (!r2.ok) {
            assert.equal(r2.field, 'clientOrderId');
            assert.match(r2.message, /operación distinta/);
        }
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('cruce fill->FX: el id de una orden filled no vale para una conversión', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'dup-xkind-01' }));
        const r = await actions.convertManualDemoCurrency(fx({ clientOrderId: 'dup-xkind-01' }));
        assert.equal(r.ok, false);
        if (!r.ok) assert.match(r.message, /operación distinta/);
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('cruce FX->fill: el id de una conversión no vale para una orden', async () => {
        const r1 = await actions.convertManualDemoCurrency(fx({ clientOrderId: 'dup-xkind-02' }));
        assert.ok(r1.ok && r1.outcome === 'filled');
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'dup-xkind-02' }));
        assert.equal(r.ok, false);
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('opciones: mismo id con otro strike es error; mismo payload es duplicate', async () => {
        const r1 = await actions.placeManualOrder(opcion({ clientOrderId: 'dup-opt-01' }));
        assert.ok(r1.ok && r1.outcome === 'filled');
        const distinto = await actions.placeManualOrder(opcion({
            clientOrderId: 'dup-opt-01',
            instrument: { kind: 'opcion', contract: { underlying: 'ASTS', expiry: '2027-01-15', strike: 60, callPut: 'call', multiplier: 100, deliverable: 'acciones', adjusted: false } },
        }));
        assert.equal(distinto.ok, false);
        const igual = await actions.placeManualOrder(opcion({ clientOrderId: 'dup-opt-01' }));
        assert.ok(igual.ok);
        if (igual.ok) assert.equal(igual.outcome, 'duplicate');
        assert.equal(modelStub.__counts().trades, 1);
    });
});
