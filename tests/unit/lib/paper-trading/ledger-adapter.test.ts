// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { docsToLedger, persistedOrder, type PersistedTradeDoc } from '@/lib/paper-trading/ledger-adapter';

const T = 1_700_000_000_000;
let seq = 0;
function doc(patch: Partial<PersistedTradeDoc>): PersistedTradeDoc {
    seq += 1;
    return {
        _id: `doc-${seq}`, kind: 'accion', symbol: 'SAN', name: 'Banco Santander',
        side: 'buy', openClose: 'open', quantity: 10, status: 'filled',
        fillPrice: 4, currency: 'EUR', fee: 0, executedAt: new Date(T + seq * 1000),
        createdAt: new Date(T + seq * 1000), clientOrderId: `ord-${seq}`, ...patch,
    };
}

describe('persistedOrder', () => {
    it('ordena por executedAt, luego createdAt, luego _id (nunca por orden de array)', () => {
        const a = doc({ executedAt: new Date(1000), createdAt: new Date(5000), _id: 'b' });
        const b = doc({ executedAt: new Date(1000), createdAt: new Date(3000), _id: 'a' });
        const c = doc({ executedAt: new Date(2000), createdAt: new Date(1000), _id: 'c' });
        expect([a, b, c].sort(persistedOrder)).toEqual([b, a, c]);
    });
    it('un executedAt que no es Date cuenta como 0 (va el primero)', () => {
        const sinFecha = doc({ executedAt: null });
        const conFecha = doc({ executedAt: new Date(1000) });
        expect([conFecha, sinFecha].sort(persistedOrder)[0]).toBe(sinFecha);
    });
});

describe('docsToLedger', () => {
    it('convierte fills válidos en entradas del libro con su tiebreak', () => {
        const d = doc({});
        const { entries, violations } = docsToLedger([d]);
        expect(violations).toEqual([]);
        expect(entries).toHaveLength(1);
        expect(entries[0]).toMatchObject({
            side: 'buy', openClose: 'open', quantity: 10, price: 4, currency: 'EUR',
            source: 'manual-simulado', clientOrderId: d.clientOrderId,
            executedAt: d.executedAt!.getTime(), tiebreak: d.createdAt!.getTime(),
        });
    });

    it('los rechazos no entran en el libro; uno CON precio es corrupción avisada', () => {
        const limpio = doc({ status: 'rejected', fillPrice: null });
        const corrupto = doc({ status: 'rejected', fillPrice: 4 });
        const { entries, violations } = docsToLedger([limpio, corrupto]);
        expect(entries).toEqual([]);
        expect(violations).toHaveLength(1);
        expect(violations[0]).toContain('rejected con fillPrice');
    });

    it('una fx válida entra como conversión con el tipo en fillPrice', () => {
        const d = doc({ kind: 'fx', fxFrom: 'EUR', fxTo: 'USD', quantity: 100, fillPrice: 1.1 });
        const { entries, violations } = docsToLedger([d]);
        expect(violations).toEqual([]);
        expect(entries[0]).toMatchObject({ kind: 'fx', from: 'EUR', to: 'USD', amountFrom: 100, rate: 1.1 });
    });

    it.each([
        ['sin executedAt', { executedAt: null }, 'fx sin executedAt válido'],
        ['from igual a to', { fxFrom: 'EUR' as const, fxTo: 'EUR' as const }, 'fx inválida'],
        ['sin divisa destino', { fxTo: null }, 'fx inválida'],
        ['tipo 0', { fillPrice: 0 }, 'fx inválida'],
        ['importe 0', { quantity: 0 }, 'fx inválida'],
    ])('una fx %s no entra y queda violation', (_e, patch, fragmento) => {
        const base = { kind: 'fx' as const, fxFrom: 'EUR' as const, fxTo: 'USD' as const, quantity: 100, fillPrice: 1.1 };
        const { entries, violations } = docsToLedger([doc({ ...base, ...patch })]);
        expect(entries).toEqual([]);
        expect(violations[0]).toContain(fragmento);
    });

    it('una opción sin contrato es corrupción visible, no se omite en silencio', () => {
        const d = doc({ kind: 'opcion', contract: null });
        const { entries, violations } = docsToLedger([d]);
        expect(entries).toEqual([]);
        expect(violations[0]).toContain('opción sin contrato');
    });

    it('un fill sin executedAt válido no entra en el libro', () => {
        const d = doc({ executedAt: null });
        const { entries, violations } = docsToLedger([d]);
        expect(entries).toEqual([]);
        expect(violations[0]).toContain('fill sin executedAt válido');
    });

    it('un fill corrupto (precio null) no entra y queda violation con su id', () => {
        const d = doc({ fillPrice: null });
        const { entries, violations } = docsToLedger([d]);
        expect(entries).toEqual([]);
        expect(violations[0]).toContain('fill corrupto');
        expect(violations[0]).toContain(String(d._id));
    });

    it('una opción válida conserva su contrato en la entrada', () => {
        const contract = { underlying: 'AAPL', callPut: 'call' as const, strike: 200, expiry: '2026-12-18', multiplier: 100, deliverable: 'acciones' as const, adjusted: false };
        const d = doc({ kind: 'opcion', contract, name: 'AAPL 2026-12-18 200 Call' });
        const { entries, violations } = docsToLedger([d]);
        expect(violations).toEqual([]);
        const entry = entries[0];
        expect('kind' in entry && entry.kind === 'fx').toBe(false);
        if (!('kind' in entry)) {
            expect(entry.instrument.kind).toBe('opcion');
            if (entry.instrument.kind === 'opcion') expect(entry.instrument.contract).toEqual(contract);
        }
    });

    it('un side desconocido se trata como compra y un openClose desconocido como apertura', () => {
        const d = doc({ side: undefined, openClose: undefined });
        const { entries } = docsToLedger([d]);
        expect(entries[0]).toMatchObject({ side: 'buy', openClose: 'open' });
    });

    it('devuelve las entradas en orden persistido aunque los docs lleguen desordenados', () => {
        const tarde = doc({ executedAt: new Date(9000), clientOrderId: 'tarde' });
        const pronto = doc({ executedAt: new Date(1000), clientOrderId: 'pronto' });
        const { entries } = docsToLedger([tarde, pronto]);
        expect(entries.map((e) => e.clientOrderId)).toEqual(['pronto', 'tarde']);
    });

    it('un documento sin _id ni clientOrderId se identifica como desconocido en la violation', () => {
        const d = doc({ _id: undefined, clientOrderId: undefined as unknown as string, fillPrice: null });
        const { violations } = docsToLedger([d]);
        expect(violations[0]).toContain('desconocido');
    });
});
