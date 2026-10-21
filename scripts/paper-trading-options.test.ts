/**
 * Guard de las reglas puras de opciones de la demo manual
 * (lib/paper-trading/options.ts): contrato, prima x100, apertura/cierre,
 * rechazo de ajustados y vencimiento sin precio inventado.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import * as opt from '../lib/paper-trading/options.ts';
import type { OptionContract } from '../lib/paper-trading/types';

const contract: OptionContract = {
    underlying: 'ASTS',
    callPut: 'call',
    strike: 50,
    expiry: '2026-12-18',
    multiplier: 100,
    deliverable: 'acciones',
    adjusted: false,
};
const NOW = Date.parse('2026-10-21T14:00:00Z');
const base = {
    contract,
    side: 'buy' as const,
    openClose: 'open' as const,
    contracts: 2,
    premium: 1.25,
    currency: 'USD' as const,
    fee: 0,
    executedAt: NOW,
    clientOrderId: 'c1',
    heldContracts: 0,
    availableCash: 1000,
};

test('prima total = prima x 100 x contratos, sin errores de coma flotante', () => {
    assert.equal(opt.premiumTotal(1.25, 2), 250);
    assert.equal(opt.premiumTotal(0.07, 3), 21);
    assert.equal(opt.premiumTotal(0.1, 3), 30);
});

test('compra para abrir: cash baja prima+fee; venta sube prima-fee', () => {
    const buy = opt.buildOptionFill({ ...base, fee: 1.3 });
    assert.equal(buy.ok, true);
    if (buy.ok) {
        assert.equal(opt.optionCashDelta(buy.value), -251.3);
        assert.equal(buy.value.source, 'manual-simulado');
    }
    const sell = opt.buildOptionFill({ ...base, side: 'sell', openClose: 'close', heldContracts: 2, fee: 1.3 });
    assert.equal(sell.ok, true);
    if (sell.ok) assert.equal(opt.optionCashDelta(sell.value), 248.7);
});

test('rechaza contratos ajustados, multiplicador no estandar y datos invalidos', () => {
    for (const bad of [
        { ...contract, adjusted: true },
        { ...contract, multiplier: 10 },
        { ...contract, strike: 0 },
        { ...contract, expiry: '2026-02-30' },
        { ...contract, callPut: 'x' as unknown as 'call' },
        { ...contract, underlying: '' },
    ]) {
        assert.equal(opt.buildOptionFill({ ...base, contract: bad }).ok, false);
    }
});

test('fase 1: sin vender para abrir ni comprar para cerrar', () => {
    assert.equal(opt.buildOptionFill({ ...base, side: 'sell', openClose: 'open' }).ok, false);
    assert.equal(opt.buildOptionFill({ ...base, side: 'buy', openClose: 'close', heldContracts: 5 }).ok, false);
});

test('cierre limitado a lo abierto; apertura limitada al saldo', () => {
    assert.equal(opt.buildOptionFill({ ...base, side: 'sell', openClose: 'close', heldContracts: 1 }).ok, false);
    assert.equal(opt.buildOptionFill({ ...base, availableCash: 249.99 }).ok, false);
    assert.equal(opt.buildOptionFill({ ...base, availableCash: 250 }).ok, true);
    assert.equal(opt.buildOptionFill({ ...base, availableCash: Number.NaN }).ok, false);
});

test('rechaza cantidad, prima, fee, fecha e id invalidos', () => {
    for (const patch of [
        { contracts: 1.5 }, { contracts: 0 }, { premium: 0 }, { premium: -1 }, { premium: Number.NaN },
        { premium: 1.23456 }, { fee: -1 }, { executedAt: 0 }, { clientOrderId: '' }, { currency: 'GBP' as 'USD' },
    ]) {
        assert.equal(opt.buildOptionFill({ ...base, ...patch }).ok, false, JSON.stringify(patch));
    }
});

test('no se opera un contrato vencido; el dia de vencimiento aun es vigente (hora NY)', () => {
    const expiryDayLate = Date.parse('2026-12-18T23:30:00Z'); // 18:30 NY
    assert.equal(opt.buildOptionFill({ ...base, executedAt: expiryDayLate }).ok, true);
    const nextDay = Date.parse('2026-12-19T12:00:00Z');
    assert.equal(opt.buildOptionFill({ ...base, executedAt: nextDay }).ok, false);
    assert.deepEqual(opt.expirationState(contract, expiryDayLate), { status: 'vigente', daysToExpiry: 0 });
    assert.equal(opt.expirationState(contract, nextDay).status, 'vencido');
});

test('vencimiento: sin dato de cierre queda pendiente, nunca se asume', () => {
    const after = Date.parse('2026-12-21T12:00:00Z');
    const none = opt.expiryOutcome(contract, after, null);
    assert.equal(none.status, 'pendiente-liquidacion');
    assert.equal(opt.expiryOutcome(contract, after, Number.NaN).status, 'pendiente-liquidacion');
    assert.deepEqual(opt.expiryOutcome(contract, after, 40), { status: 'sin-valor', intrinsicPerShare: 0 });
    assert.deepEqual(opt.expiryOutcome(contract, after, 50), { status: 'sin-valor', intrinsicPerShare: 0 });
    const itm = opt.expiryOutcome(contract, after, 55);
    assert.equal(itm.status, 'pendiente-liquidacion');
    if (itm.status === 'pendiente-liquidacion') assert.equal(itm.intrinsicPerShare, 5);
    assert.equal(opt.expiryOutcome(contract, NOW, 55).status, 'vigente');
});

test('put: valor intrinseco = strike - subyacente', () => {
    const put = { ...contract, callPut: 'put' as const };
    assert.equal(opt.intrinsicValue(put, 42), 8);
    assert.equal(opt.intrinsicValue(put, 60), 0);
});
