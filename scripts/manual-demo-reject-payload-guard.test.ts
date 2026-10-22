/**
 * Guard fix-2: las filas RECHAZADAS nuevas persisten un snapshot normalizado
 * del payload pedido (requestPayload) y la idempotencia compara el payload
 * COMPLETO también contra rechazos (precio, comisión y fecha incluidos).
 *
 * Contrato de outcome: contra una fila rechazada, el duplicado llega como
 * outcome 'duplicate' CON la razón persistida en `reason` (vía temprana de
 * duplicateResult); en la carrera E11000 de recordRejection llega como
 * outcome 'rejected' con la razón del ganador.
 *
 * LEGACY (opción A acordada): filas rechazadas sin snapshot (anteriores a
 * fix-2) o con shape inválida comparan SOLO el subconjunto persistido
 * (instrumento/lado/fase/cantidad/divisa) y conservan la razón del rechazo;
 * la igualdad completa queda DESCONOCIDA y nunca se afirma precio/fee/fecha.
 * Una shape inválida es desconocido, nunca excepción ni falso match.
 * El snapshot NUNCA sale al cliente (toRow no lo mapea).
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-reject-payload-guard.test.ts
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
    __seedTrade(doc: Record<string, unknown>): void;
    __snapshot(): { trades: Array<Record<string, unknown>> };
};

const USER = { id: 'guard-rej-1', email: 'rej@demo.test', name: 'Rej' };
let orderSeq = 0;
const oid = () => `guard-rej-${String(++orderSeq).padStart(4, '0')}`;
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
    quantity: 100_000,
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
    amount: 200_000,
    rate: 1.1,
    executedAt: NOW - 40_000,
    clientOrderId: oid(),
    ...over,
});

/** Fila rejected como la grabaría un ganador de carrera; sin requestPayload salvo que se pase (legacy). */
function rejectedRow(id: string, extra: Record<string, unknown> = {}) {
    return {
        userId: USER.id, clientOrderId: id, kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
        contract: null, side: 'buy', openClose: 'open', fxFrom: null, fxTo: null, quantity: 100_000,
        status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0, fillSource: 'manual-simulado',
        executedAt: null, rejectReason: 'REASON-GANADOR', ...extra,
    };
}

function snapshotOrden(over: Record<string, unknown> = {}) {
    return {
        v: 1, kind: 'accion', symbol: 'BBVA.MC', contractKey: null, side: 'buy', openClose: 'open',
        quantity: 100_000, currency: 'EUR', price: 999_999, fee: 0, executedAtMs: NOW - 60_000, ...over,
    };
}

/** Inserta directamente una fila rechazada (p.ej. legacy) para ejercer la vía temprana de duplicateResult. */
function seedRejectedRow(id: string, extra: Record<string, unknown> = {}) {
    modelStub.__seedTrade(rejectedRow(id, extra));
    assert.equal(modelStub.__counts().trades, 1);
}

beforeEach(() => {
    modelStub.__reset();
    orderSeq = 0;
    (globalThis as Record<string, unknown>).__MANUAL_DEMO_GUARD_USER__ = USER;
});

describe('fix-2: rechazos con snapshot comparable', () => {
    it('rechazo + reintento idéntico: duplicate con la razón persistida; el snapshot queda grabado', async () => {
        const r1 = await actions.placeManualOrder(accion({ clientOrderId: 'rej-same-01', quantity: 100_000, price: 999_999 }));
        assert.ok(r1.ok && r1.outcome === 'rejected');
        const r2 = await actions.placeManualOrder(accion({ clientOrderId: 'rej-same-01', quantity: 100_000, price: 999_999 }));
        assert.ok(r2.ok);
        if (r2.ok) {
            assert.equal(r2.outcome, 'duplicate');
            assert.equal(r2.reason, r1.ok && r1.outcome === 'rejected' ? r1.reason : null);
        }
        assert.equal(modelStub.__counts().trades, 1);
        const raw = modelStub.__snapshot().trades[0] as { requestPayload?: { price?: number } };
        assert.equal(raw.requestPayload?.price, 999_999);
    });

    it('rechazo + otra COMISIÓN: conflicto explícito', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'rej-fee-01', quantity: 100_000, price: 10, fee: 5 }));
        const r2 = await actions.placeManualOrder(accion({ clientOrderId: 'rej-fee-01', quantity: 100_000, price: 10, fee: 7 }));
        assert.equal(r2.ok, false);
        if (!r2.ok) assert.equal(r2.field, 'clientOrderId');
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('rechazo + otra FECHA de ejecución: conflicto explícito', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'rej-fec-01', quantity: 100_000, price: 999_999, executedAt: NOW - 60_000 }));
        const r2 = await actions.placeManualOrder(accion({ clientOrderId: 'rej-fec-01', quantity: 100_000, price: 999_999, executedAt: NOW - 30_000 }));
        assert.equal(r2.ok, false);
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('LEGACY sin snapshot: mismo subconjunto con otro precio -> duplicate con razón (igualdad completa desconocida)', async () => {
        await seedRejectedRow('rej-legacy-01', { rejectReason: 'REASON-LEGACY-PERSISTIDA' });
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'rej-legacy-01', quantity: 100_000, price: 888_888 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'duplicate');
            assert.equal(r.reason, 'REASON-LEGACY-PERSISTIDA');
        }
        assert.equal(modelStub.__counts().trades, 1);
        const raw = modelStub.__snapshot().trades[0];
        assert.ok(!('requestPayload' in raw) || raw.requestPayload == null);
    });

    it('LEGACY sin snapshot: subconjunto distinto (otro símbolo) -> conflicto explícito', async () => {
        await seedRejectedRow('rej-legacy-02');
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'rej-legacy-02', quantity: 100_000, instrument: { kind: 'accion', symbol: 'SAN.MC', name: 'SAN' } }));
        assert.equal(r.ok, false);
        if (!r.ok) assert.equal(r.field, 'clientOrderId');
    });

    it('shape inválida (string basura): tratada como legacy, subconjunto + razón, sin crash', async () => {
        await seedRejectedRow('rej-bad-01', { requestPayload: 'garbage-no-un-objeto' });
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'rej-bad-01', quantity: 100_000, price: 123_456 }));
        assert.ok(r.ok);
        if (r.ok) assert.equal(r.outcome, 'duplicate');
    });

    it('shape inválida (versión desconocida v:2): tratada como legacy, sin crash ni falso match', async () => {
        await seedRejectedRow('rej-bad-02', { requestPayload: snapshotOrden({ v: 2 }) });
        const r = await actions.placeManualOrder(accion({ clientOrderId: 'rej-bad-02', quantity: 100_000, price: 999_999 }));
        assert.ok(r.ok);
        if (r.ok) assert.equal(r.outcome, 'duplicate');
    });

    it('FX rechazada: mismo payload -> duplicate con razón; otro importe u otro rate -> conflicto', async () => {
        const r1 = await actions.convertManualDemoCurrency(fx({ clientOrderId: 'rej-fx-01' }));
        assert.ok(r1.ok && r1.outcome === 'rejected');
        const dup = await actions.convertManualDemoCurrency(fx({ clientOrderId: 'rej-fx-01' }));
        assert.ok(dup.ok);
        if (dup.ok) assert.equal(dup.outcome, 'duplicate');
        const otroImporte = await actions.convertManualDemoCurrency(fx({ clientOrderId: 'rej-fx-01', amount: 250_000 }));
        assert.equal(otroImporte.ok, false);
        await actions.convertManualDemoCurrency(fx({ clientOrderId: 'rej-fx-02' }));
        const otroRate = await actions.convertManualDemoCurrency(fx({ clientOrderId: 'rej-fx-02', rate: 1.2 }));
        assert.equal(otroRate.ok, false);
        assert.equal(modelStub.__counts().trades, 2);
    });

    it('opción rechazada: mismo contrato duplicate; otro strike -> conflicto', async () => {
        const r1 = await actions.placeManualOrder(opcion({ clientOrderId: 'rej-opt-01' }));
        assert.ok(r1.ok && r1.outcome === 'rejected');
        const dup = await actions.placeManualOrder(opcion({ clientOrderId: 'rej-opt-01' }));
        assert.ok(dup.ok);
        if (dup.ok) assert.equal(dup.outcome, 'duplicate');
        const otroStrike = await actions.placeManualOrder(opcion({
            clientOrderId: 'rej-opt-01',
            instrument: { kind: 'opcion', contract: { underlying: 'ASTS', expiry: '2027-01-15', strike: 60, callPut: 'call', multiplier: 100, deliverable: 'acciones', adjusted: false } },
        }));
        assert.equal(otroStrike.ok, false);
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('alias: rechazada con otro NAME y mismo resto -> duplicate (el nombre no crea falso conflicto)', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'rej-alias-01', quantity: 100_000, price: 999_999 }));
        const r2 = await actions.placeManualOrder(accion({
            clientOrderId: 'rej-alias-01', quantity: 100_000, price: 999_999,
            instrument: { kind: 'accion', symbol: 'BBVA.MC', name: 'Banco Bilbao Vizcaya Argentaria' },
        }));
        assert.ok(r2.ok);
        if (r2.ok) assert.equal(r2.outcome, 'duplicate');
        assert.equal(modelStub.__counts().trades, 1);
    });

    it('carrera E11000 en recordRejection con snapshot: mismo payload -> rejected con razón del ganador; distinto -> conflicto', async () => {
        await actions.placeManualOrder(accion({ quantity: 10, price: 10, executedAt: NOW - 50_000 })); // posición 10
        const snapVenta = { v: 1, kind: 'accion', symbol: 'BBVA.MC', contractKey: null, side: 'sell', openClose: 'close', quantity: 5, currency: 'EUR', price: 12, fee: 0, executedAtMs: NOW - 60_000 };
        modelStub.__dupNextTradeCreate({
            userId: USER.id, clientOrderId: 'rej-race-01', kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
            contract: null, side: 'sell', openClose: 'close', fxFrom: null, fxTo: null,
            quantity: 5, status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0,
            fillSource: 'manual-simulado', executedAt: null, rejectReason: 'REASON-GANADOR-SNAPSHOT',
            requestPayload: snapVenta,
        });
        // Venta antedatada ANTES de la compra -> divergencia temporal -> recordRejection -> E11000.
        const mismo = await actions.placeManualOrder(accion({ clientOrderId: 'rej-race-01', side: 'sell', quantity: 5, price: 12, executedAt: NOW - 60_000 }));
        assert.ok(mismo.ok);
        if (mismo.ok) {
            assert.equal(mismo.outcome, 'rejected');
            assert.equal(mismo.reason, 'REASON-GANADOR-SNAPSHOT');
        }
        // Mismo id, ganador con snapshot de precio 12, perdedor pide precio 13 -> conflicto.
        modelStub.__dupNextTradeCreate({
            userId: USER.id, clientOrderId: 'rej-race-02', kind: 'accion', symbol: 'BBVA.MC', name: 'BBVA',
            contract: null, side: 'sell', openClose: 'close', fxFrom: null, fxTo: null,
            quantity: 5, status: 'rejected', fillPrice: null, currency: 'EUR', fee: 0,
            fillSource: 'manual-simulado', executedAt: null, rejectReason: 'REASON-GANADOR-SNAPSHOT',
            requestPayload: snapVenta,
        });
        const distinto = await actions.placeManualOrder(accion({ clientOrderId: 'rej-race-02', side: 'sell', quantity: 5, price: 13, executedAt: NOW - 60_000 }));
        assert.equal(distinto.ok, false);
        if (!distinto.ok) assert.match(distinto.message, /operación distinta/);
        assert.equal(modelStub.__counts().trades, 3); // compra + 2 ganadores; los perdedores no graban
    });

    it('el snapshot NO sale al cliente: getManualDemoOrders no expone requestPayload', async () => {
        await actions.placeManualOrder(accion({ clientOrderId: 'rej-surf-01', quantity: 100_000, price: 999_999 }));
        const hist = await actions.getManualDemoOrders();
        assert.ok(hist.ok);
        if (hist.ok) {
            const row = hist.orders.find((o: { clientOrderId: string }) => o.clientOrderId === 'rej-surf-01');
            assert.ok(row);
            assert.ok(!('requestPayload' in row));
        }
        const raw = modelStub.__snapshot().trades[0] as { requestPayload?: { price?: number } };
        assert.equal(raw.requestPayload?.price, 999_999); // el test no es vacío: el snapshot existe en crudo
    });
});
