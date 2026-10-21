/**
 * Guard de alineación fast-path/replay en el redondeo a céntimos (P3):
 * decide() debe decidir con la MISMA cifra r2 que aplicaría el libro.
 * Cubre el falso rechazo de una compra globalmente válida (coste bruto
 * sub-céntimo por encima del cash pero r2(cost) <= cash) y las fronteras
 * simétricas en compra y venta. Opciones no aplican: prima x 100 x
 * contratos enteros siempre es exacta a céntimos; FX no tiene fast path.
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-rounding-guard.test.ts
 */
import { beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./manual-demo-guard.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
const actions = await import('../lib/actions/manual-demo.actions.ts');
const modelStub = (await import('@/database/models/manual-demo.model')) as unknown as {
    __reset(): void;
};

const USER = { id: 'guard-round-1', email: 'round@demo.test', name: 'Round' };
let orderSeq = 0;
const oid = () => `guard-round-${String(++orderSeq).padStart(4, '0')}`;
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

beforeEach(() => {
    modelStub.__reset();
    orderSeq = 0;
    (globalThis as Record<string, unknown>).__MANUAL_DEMO_GUARD_USER__ = USER;
});

describe('alineación del redondeo fast-path/replay (r2)', () => {
    it('compra con coste bruto sub-céntimo sobre el cash pero r2(cost) <= cash: ACEPTADA (el libro la aplica)', async () => {
        // cash exacto 31,00
        const seed = await actions.placeManualOrder(accion({ price: 99_969 }));
        assert.ok(seed.ok);
        // coste bruto 31,0049 > 31,00; r2 = 31,00 = cash
        const r = await actions.placeManualOrder(accion({ price: 31.0049 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 0);
            assert.equal(r.state.positions.length, 1); // misma accion: un solo renglon con 2 lotes
            assert.equal(r.state.positions[0].quantity, 2);
            assert.equal(r.state.violations.length, 0);
        }
    });

    it('frontera simétrica: coste cuyo r2 SUPERA el cash sigue rechazado', async () => {
        await actions.placeManualOrder(accion({ price: 99_969 })); // cash 31,00
        const r = await actions.placeManualOrder(accion({ price: 31.0051 })); // r2 = 31,01 > 31,00
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected');
            assert.match(r.reason ?? '', /insuficiente/);
            assert.equal(r.state.cashEUR, 31);
            assert.equal(r.state.positions.length, 1);
        }
    });

    it('compra múltiple con decimales acumulados: 3 x 10,3333 (bruto 30,9999) con cash 31,00: ACEPTADA', async () => {
        await actions.placeManualOrder(accion({ price: 99_969 })); // cash 31,00
        const r = await actions.placeManualOrder(accion({ quantity: 3, price: 10.3333 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 0);
        }
    });

    it('venta: fee (siempre 2 decimales) por encima de cash + r2(proceeds): rechazada ya en fast path', async () => {
        // La comision admite como maximo 2 decimales: con cash/proceeds a
        // centimos no existe banda sub-centimo en la venta; la formula de
        // decide queda alineada con el replay por construccion.
        await actions.placeManualOrder(accion({ price: 100_000 })); // cash 0, posicion 1
        const r = await actions.placeManualOrder(accion({ side: 'sell', price: 31.0049, fee: 31.01 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'rejected'); // cash 0 + r2(31,0049) = 31,00 < 31,01
            assert.match(r.reason ?? '', /sobregiro/);
            assert.equal(r.state.positions.length, 1);
        }
    });

    it('venta frontera exacta redondeada: fee == r2(proceeds) + cash: ACEPTADA', async () => {
        await actions.placeManualOrder(accion({ price: 100_000 }));
        const r = await actions.placeManualOrder(accion({ side: 'sell', price: 31.0049, fee: 31 }));
        assert.ok(r.ok);
        if (r.ok) {
            assert.equal(r.outcome, 'filled');
            assert.equal(r.state.cashEUR, 0);
            assert.equal(r.state.positions.length, 0);
        }
    });

    it('la compra aceptada en la frontera es idempotente (mismo clientOrderId -> duplicate filled)', async () => {
        await actions.placeManualOrder(accion({ price: 99_969 }));
        const order = accion({ price: 31.0049, clientOrderId: 'guard-round-dup-01' });
        const r1 = await actions.placeManualOrder(order);
        const r2 = await actions.placeManualOrder(order);
        assert.ok(r1.ok && r2.ok);
        if (r1.ok && r2.ok) {
            assert.equal(r1.outcome, 'filled');
            assert.equal(r2.outcome, 'duplicate');
            assert.equal(r2.state.cashEUR, 0);
        }
    });
});
