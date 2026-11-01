import { describe, expect, it } from 'vitest';
import {
    buildOptionFill, expirationState, expiryBadge, expiryOutcome,
    intrinsicValue, isRealDate, newYorkDate, optionCashDelta,
    premiumTotal, validateOptionContract,
} from '@/lib/paper-trading/options';
import type { OptionContract } from '@/lib/paper-trading/types';
import type { OptionOrderInput } from '@/lib/paper-trading/options';

const CONTRACT: OptionContract = {
    underlying: 'SAN', callPut: 'call', strike: 5, expiry: '2026-12-18',
    multiplier: 100, deliverable: 'acciones', adjusted: false,
};
// 2026-06-01 12:00 UTC: fecha civil en Nueva York = 2026-06-01.
const NOW = Date.UTC(2026, 5, 1, 12);

function order(over: Partial<OptionOrderInput> = {}): OptionOrderInput {
    return {
        contract: CONTRACT, side: 'buy', openClose: 'open', contracts: 2,
        premium: 1.5, currency: 'EUR', fee: 1, executedAt: NOW,
        clientOrderId: 'o1', heldContracts: 0, availableCash: 10_000, ...over,
    };
}

describe('validateOptionContract', () => {
    it('accepts a standard OCC contract', () => {
        expect(validateOptionContract(CONTRACT)).toEqual({ ok: true, value: CONTRACT });
    });
    it.each([
        [{ underlying: '' }, 'Subyacente inválido'],
        [{ underlying: '1SAN' }, 'Subyacente inválido'],
        [{ callPut: 'straddle' as never }, 'Tipo debe ser call o put'],
        [{ strike: 0 }, 'Strike debe ser un número mayor que 0'],
        [{ strike: -3 }, 'Strike debe ser un número mayor que 0'],
        [{ expiry: '2026-13-01' }, 'Vencimiento inválido'],
        [{ expiry: '2026-02-30' }, 'Vencimiento inválido'],
        [{ deliverable: 'cash' as never }, 'entrega de acciones'],
        [{ adjusted: true }, 'Contrato ajustado'],
        [{ multiplier: 10 }, 'multiplicador 100'],
    ])('rejects %o', (over, msg) => {
        const r = validateOptionContract({ ...CONTRACT, ...over });
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain(msg);
    });
});

describe('isRealDate', () => {
    it.each(['2026-12-18', '2024-02-29'])('accepts %s', (iso) => expect(isRealDate(iso)).toBe(true));
    it.each(['2026-13-01', '2026-02-30', '2026-1-1', '18-12-2026', 'abcd-ef-gh'])('rejects %s', (iso) => expect(isRealDate(iso)).toBe(false));
});

describe('newYorkDate / expiryBadge / expirationState', () => {
    it('uses the New York civil date, not UTC or the user tz', () => {
        // 2026-06-02 01:00 UTC is still 2026-06-01 in New York (EDT, UTC-4).
        expect(newYorkDate(Date.UTC(2026, 5, 2, 1))).toBe('2026-06-01');
        expect(newYorkDate(Date.UTC(2026, 5, 2, 5))).toBe('2026-06-02');
    });
    it('badge: vigente / vence-hoy / vencida around the expiry date', () => {
        const onExpiry = Date.UTC(2026, 11, 18, 12); // NY date = 2026-12-18
        expect(expiryBadge('2026-12-18', NOW)).toBe('vigente');
        expect(expiryBadge('2026-12-18', onExpiry)).toBe('vence-hoy');
        expect(expiryBadge('2026-12-18', Date.UTC(2026, 11, 19, 12))).toBe('vencida');
    });
    it('expirationState counts NY civil days and marks vencido only after the day', () => {
        const onExpiry = Date.UTC(2026, 11, 18, 12);
        expect(expirationState(CONTRACT, onExpiry)).toEqual({ status: 'vigente', daysToExpiry: 0 });
        expect(expirationState(CONTRACT, Date.UTC(2026, 11, 19, 12))).toEqual({ status: 'vencido', daysToExpiry: -1 });
    });
});

describe('premiumTotal / optionCashDelta', () => {
    it('premium = price per share x 100 x contracts', () => {
        expect(premiumTotal(1.5, 2)).toBe(300);
        expect(premiumTotal(0.05, 1)).toBe(5);
    });
    it('buy delta = -(premium + fee), sell delta = +(premium - fee), in cents', () => {
        const base = { price: 1.5, quantity: 2, fee: 1, instrument: { kind: 'opcion' as const, contract: CONTRACT, name: '' } };
        expect(optionCashDelta({ ...base, side: 'buy' })).toBe(-301);
        expect(optionCashDelta({ ...base, side: 'sell' })).toBe(299);
    });
    it('rounds fractional-premium totals to cents', () => {
        expect(optionCashDelta({ side: 'buy', price: 0.3333, quantity: 3, fee: 0, instrument: { kind: 'opcion' as const, contract: CONTRACT, name: '' } })).toBe(-99.99);
    });
});

describe('buildOptionFill', () => {
    it('builds a buy/open fill with OCC-style name', () => {
        const r = buildOptionFill(order());
        expect(r.ok).toBe(true);
        if (r.ok) {
            expect(r.value).toMatchObject({
                side: 'buy', openClose: 'open', quantity: 2, price: 1.5,
                currency: 'EUR', source: 'manual-simulado', clientOrderId: 'o1',
            });
            expect(r.value.instrument.name).toBe('SAN 2026-12-18 5 Call');
        }
    });
    it('rejects sell-to-open (phase 1: no shorts)', () => {
        const r = buildOptionFill(order({ side: 'sell', openClose: 'open' }));
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('comprar para abrir y vender para cerrar');
    });
    it.each([
        [{ contracts: 0 }, 'entero mayor que 0'],
        [{ contracts: 1.5 }, 'entero mayor que 0'],
        [{ premium: 0 }, 'prima debe ser mayor que 0'],
        [{ premium: 1.00001 }, 'máximo 4 decimales'],
        [{ fee: -1 }, 'comisión no puede ser negativa'],
        [{ executedAt: 0 }, 'Fecha de ejecución inválida'],
        [{ clientOrderId: '' }, 'clientOrderId'],
    ])('rejects invalid input %o', (over, msg) => {
        const r = buildOptionFill(order(over));
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain(msg);
    });
    it('rejects an order executed after expiry', () => {
        const r = buildOptionFill(order({ executedAt: Date.UTC(2027, 0, 10, 12) }));
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('ya venció');
    });
    it('rejects closing more contracts than held', () => {
        const r = buildOptionFill(order({ side: 'sell', openClose: 'close', contracts: 3, heldContracts: 2 }));
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('solo hay 2 abiertos');
    });
    it('rejects a buy without enough cash (no implicit overdraft)', () => {
        const r = buildOptionFill(order({ availableCash: 200 })); // cost = 300 + 1 fee
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('Saldo EUR insuficiente');
    });
    it('rejects a close whose fee exceeds cash + proceeds', () => {
        const r = buildOptionFill(order({ side: 'sell', openClose: 'close', heldContracts: 5, availableCash: 0, premium: 1, fee: 250 }));
        expect(r.ok).toBe(false);
        if (!r.ok) expect(r.reason).toContain('supera el efectivo disponible');
    });
});

describe('intrinsicValue / expiryOutcome', () => {
    it('intrinsic value floors at 0', () => {
        expect(intrinsicValue(CONTRACT, 7)).toBe(2);
        expect(intrinsicValue(CONTRACT, 4)).toBe(0);
        expect(intrinsicValue({ ...CONTRACT, callPut: 'put' }, 4)).toBe(1);
    });
    it('vigente before expiry regardless of price', () => {
        expect(expiryOutcome(CONTRACT, NOW, null)).toEqual({ status: 'vigente' });
    });
    it('after expiry with no dated close: pendiente, never assumes ITM/OTM', () => {
        const r = expiryOutcome(CONTRACT, Date.UTC(2027, 0, 10, 12), null);
        expect(r).toMatchObject({ status: 'pendiente-liquidacion', intrinsicPerShare: null });
    });
    it('after expiry OTM: sin-valor', () => {
        expect(expiryOutcome(CONTRACT, Date.UTC(2027, 0, 10, 12), 4)).toEqual({ status: 'sin-valor', intrinsicPerShare: 0 });
    });
    it('after expiry ITM: pendiente-liquidacion with intrinsic per share', () => {
        const r = expiryOutcome(CONTRACT, Date.UTC(2027, 0, 10, 12), 7);
        expect(r).toMatchObject({ status: 'pendiente-liquidacion', intrinsicPerShare: 2 });
    });
});

describe('instrumentKey / parseOptionKey', () => {
    it('option key round-trips through parseOptionKey', async () => {
        const { instrumentKey, parseOptionKey } = await import('@/lib/paper-trading/types');
        const key = instrumentKey({ kind: 'opcion', name: '', contract: CONTRACT });
        expect(key).toBe('O:SAN:2026-12-18:call:5:100');
        expect(parseOptionKey(key)).toEqual({ underlying: 'SAN', expiry: '2026-12-18', callPut: 'call', strike: 5, multiplier: 100 });
    });
    it('stock key is just the uppercased symbol and never parses as an option', async () => {
        const { instrumentKey, parseOptionKey } = await import('@/lib/paper-trading/types');
        expect(instrumentKey({ kind: 'accion', symbol: 'san', name: 'SAN' })).toBe('A:SAN');
        expect(parseOptionKey('A:SAN')).toBeNull();
    });
    it.each([
        'O:SAN:2026-12-18:call:5:10', // multiplicador no estandar
        'O:SAN:18-12-2026:call:5:100', // fecha con formato incorrecto
        'O::2026-12-18:call:5:100', // subyacente vacio
        'O:SAN:2026-12-18:call:0:100', // strike no positivo
        'X:SAN:2026-12-18:call:5:100', // prefijo desconocido
    ])('parseOptionKey rejects malformed key %s', async (key) => {
        const { parseOptionKey } = await import('@/lib/paper-trading/types');
        expect(parseOptionKey(key)).toBeNull();
    });
});
