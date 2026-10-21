/**
 * Guard del adaptador persistencia -> libro (P1): lo corrupto produce
 * violation visible, nunca omisión silenciosa.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
import { docsToLedger, type PersistedTradeDoc } from '../lib/paper-trading/ledger-adapter.ts';

const base: PersistedTradeDoc = {
    _id: 'd1', kind: 'accion', symbol: 'ASTS', name: 'ASTS', side: 'buy', openClose: 'open',
    quantity: 10, status: 'filled', fillPrice: 50, currency: 'USD', fee: 0,
    executedAt: new Date(1_700_000_000_000), clientOrderId: 'c1', createdAt: new Date(1_700_000_000_100),
};

test('doc sano -> fill con tiebreak=createdAt y executedAt en ms', () => {
    const { entries, violations } = docsToLedger([base]);
    assert.equal(violations.length, 0);
    assert.equal(entries.length, 1);
    const f = entries[0] as { executedAt: number; tiebreak?: number };
    assert.equal(f.executedAt, 1_700_000_000_000);
    assert.equal(f.tiebreak, 1_700_000_000_100);
});

test('filled sin precio -> violation, no entra en el libro', () => {
    const { entries, violations } = docsToLedger([{ ...base, _id: 'd2', fillPrice: null }]);
    assert.equal(entries.length, 0);
    assert.ok(violations.some((v) => v.includes('d2') && v.includes('corrupto')));
});

test('rejected con precio -> violation de corrupción; rejected limpio se queda fuera sin ruido', () => {
    const { entries, violations } = docsToLedger([
        { ...base, _id: 'd3', status: 'rejected', fillPrice: 10 },
        { ...base, _id: 'd4', status: 'rejected', fillPrice: null },
    ]);
    assert.equal(entries.length, 0);
    assert.equal(violations.length, 1);
    assert.ok(violations[0].includes('d3'));
});

test('fx con from === to persistida -> violation, no crea dinero', () => {
    const { entries, violations } = docsToLedger([
        { ...base, _id: 'd5', kind: 'fx', fxFrom: 'EUR', fxTo: 'EUR', fillPrice: 2, quantity: 100 },
    ]);
    assert.equal(entries.length, 0);
    assert.ok(violations.some((v) => v.includes('d5') && v.includes('fx inválida')));
});
