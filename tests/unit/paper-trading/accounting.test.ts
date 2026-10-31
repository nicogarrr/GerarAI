import { describe, expect, it } from 'vitest';
import { computeManualDemoAccount } from '@/lib/paper-trading/accounting';
import type { Fill, FxConversion, Instrument } from '@/lib/paper-trading/types';

const SAN: Instrument = { kind: 'accion', symbol: 'SAN', name: 'Banco Santander' };
const SAN_OPT: Instrument = {
    kind: 'opcion',
    name: 'SAN CALL',
    contract: {
        underlying: 'SAN', callPut: 'call', strike: 5, expiry: '2026-12-18',
        multiplier: 100, deliverable: 'acciones', adjusted: false,
    },
};

let seq = 0;
function buy(over: Partial<Fill> = {}): Fill {
    return {
        instrument: SAN, side: 'buy', openClose: 'open', quantity: 10, price: 4,
        currency: 'EUR', fee: 0, executedAt: 1_000 + seq++, source: 'manual-simulado',
        clientOrderId: `b${seq}`, ...over,
    };
}
function sell(over: Partial<Fill> = {}): Fill {
    return {
        instrument: SAN, side: 'sell', openClose: 'close', quantity: 10, price: 5,
        currency: 'EUR', fee: 0, executedAt: 1_000 + seq++, source: 'manual-simulado',
        clientOrderId: `s${seq}`, ...over,
    };
}
function fx(over: Partial<FxConversion> = {}): FxConversion {
    return {
        kind: 'fx', from: 'EUR', to: 'USD', amountFrom: 100, rate: 1.1,
        executedAt: 1_000 + seq++, source: 'manual-simulado', clientOrderId: `f${seq}`, ...over,
    };
}

describe('paper-trading accounting (computeAccountState)', () => {
    it('empty ledger returns starting cash and no positions', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, []);
        expect(s.cashByCurrency).toEqual({ EUR: 1000, USD: 0 });
        expect(s.positions).toEqual([]);
        expect(s.violations).toEqual([]);
        expect(s.realizedPnlByCurrency).toEqual({ EUR: 0, USD: 0 });
    });

    it('buy spends cash with fee and opens a FIFO lot at avg cost', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [buy({ quantity: 10, price: 4, fee: 1 })]);
        expect(s.cashByCurrency.EUR).toBe(959); // 1000 - (10*4 + 1)
        expect(s.positions).toHaveLength(1);
        expect(s.positions[0]).toMatchObject({ instrumentKey: 'A:SAN', quantity: 10, avgCost: 4, currency: 'EUR' });
        expect(s.violations).toEqual([]);
    });

    it('FIFO consumes the oldest lot first regardless of array order', () => {
        // Deliberately out of order: the sell and the second buy come first in the array.
        const entries = [
            sell({ price: 10, quantity: 10, executedAt: 3000 }),
            buy({ price: 8, quantity: 10, executedAt: 2000 }),
            buy({ price: 4, quantity: 10, executedAt: 1000 }),
        ];
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, entries);
        // FIFO sells the 4 EUR lot: pnl = 10 * (10 - 4) = 60
        expect(s.realizedPnlByCurrency.EUR).toBe(60);
        // Remaining lot is the 8 EUR one
        expect(s.positions[0]).toMatchObject({ quantity: 10, avgCost: 8 });
        expect(s.violations).toEqual([]);
    });

    it('tiebreak decides between fills with identical executedAt', () => {
        // Same executedAt: the cheap lot has the LATER tiebreak, so the 4 EUR
        // lot is still older only if its tiebreak is smaller. Here expensive
        // lot has smaller tiebreak -> it is sold first.
        const entries = [
            buy({ price: 8, quantity: 10, executedAt: 1000, tiebreak: 1 }),
            buy({ price: 4, quantity: 10, executedAt: 1000, tiebreak: 2 }),
            sell({ price: 10, quantity: 10, executedAt: 2000, tiebreak: 3 }),
        ];
        const s = computeManualDemoAccount({ EUR: 10_000, USD: 0 }, entries);
        expect(s.realizedPnlByCurrency.EUR).toBe(20); // 10 * (10 - 8)
        expect(s.positions[0]).toMatchObject({ quantity: 10, avgCost: 4 });
    });

    it('partial sell consumes lots in order and realizes per-lot pnl', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [
            buy({ price: 4, quantity: 10 }),
            buy({ price: 6, quantity: 10 }),
            sell({ price: 5, quantity: 15 }),
        ]);
        // 10 from lot@4 (+10) and 5 from lot@6 (-5) => +5
        expect(s.realizedPnlByCurrency.EUR).toBe(5);
        expect(s.positions[0]).toMatchObject({ quantity: 5, avgCost: 6 });
    });

    it('oversell rejects the whole order: no cash, no lots touched', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [
            buy({ quantity: 5, price: 4 }),
            sell({ quantity: 6, price: 10 }),
        ]);
        expect(s.violations).toHaveLength(1);
        expect(s.violations[0]).toContain('orden rechazada entera');
        expect(s.cashByCurrency.EUR).toBe(980); // only the buy applied
        expect(s.positions[0]).toMatchObject({ quantity: 5 });
        expect(s.realizedPnlByCurrency.EUR).toBe(0);
    });

    it('buy without enough cash in its currency is rejected (no implicit overdraft)', () => {
        const s = computeManualDemoAccount({ EUR: 30, USD: 10_000 }, [buy({ quantity: 10, price: 4 })]);
        expect(s.violations).toHaveLength(1);
        expect(s.violations[0]).toContain('saldo EUR insuficiente');
        expect(s.cashByCurrency).toEqual({ EUR: 30, USD: 10_000 });
        expect(s.positions).toEqual([]);
    });

    it('sell whose fee exceeds cash+proceeds is rejected on its date', () => {
        const s = computeManualDemoAccount({ EUR: 40, USD: 0 }, [
            buy({ quantity: 10, price: 4, fee: 0 }), // cash -> 0
            sell({ quantity: 10, price: 4.5, fee: 50 }), // proceeds 45 < fee 50
        ]);
        expect(s.violations).toHaveLength(1);
        expect(s.violations[0]).toContain('comisión');
        expect(s.cashByCurrency.EUR).toBe(0);
        expect(s.positions[0]).toMatchObject({ quantity: 10 });
    });

    it('separates FIFO books per currency for the same symbol', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 1000 }, [
            buy({ quantity: 10, price: 4, currency: 'EUR' }),
            buy({ quantity: 10, price: 5, currency: 'USD' }),
            sell({ quantity: 10, price: 6, currency: 'USD' }),
        ]);
        expect(s.violations).toEqual([]);
        expect(s.realizedPnlByCurrency.USD).toBe(10); // 10 * (6-5)
        expect(s.realizedPnlByCurrency.EUR).toBe(0);
        expect(s.positions).toHaveLength(1);
        expect(s.positions[0]).toMatchObject({ currency: 'EUR', quantity: 10, avgCost: 4 });
    });

    it('applies the option multiplier to cost and realized pnl', () => {
        const s = computeManualDemoAccount({ EUR: 0, USD: 10_000 }, [
            buy({ instrument: SAN_OPT, quantity: 2, price: 1, currency: 'USD' }), // 2*1*100 = 200
            sell({ instrument: SAN_OPT, quantity: 2, price: 1.5, currency: 'USD' }),
        ]);
        expect(s.violations).toEqual([]);
        expect(s.cashByCurrency.USD).toBe(10_100); // -200 +300
        expect(s.realizedPnlByCurrency.USD).toBe(100); // 2 * 0.5 * 100
        expect(s.positions).toEqual([]);
    });

    it('fx conversion moves cash between currencies at the given rate', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx({ amountFrom: 100, rate: 1.1 })]);
        expect(s.violations).toEqual([]);
        expect(s.cashByCurrency).toEqual({ EUR: 900, USD: 110 });
    });

    it('fx with same from/to is rejected: it would create money', () => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx({ from: 'EUR', to: 'EUR' })]);
        expect(s.violations).toHaveLength(1);
        expect(s.violations[0]).toContain('origen y destino iguales');
        expect(s.cashByCurrency.EUR).toBe(1000);
    });

    it.each([
        [{ amountFrom: 0 }, 'importe o tipo inválido'],
        [{ amountFrom: -5 }, 'importe o tipo inválido'],
        [{ amountFrom: Number.NaN }, 'importe o tipo inválido'],
        [{ rate: 0 }, 'importe o tipo inválido'],
        [{ rate: -1.2 }, 'importe o tipo inválido'],
    ])('fx with invalid input %o is rejected', (over, msg) => {
        const s = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx(over)]);
        expect(s.violations).toHaveLength(1);
        expect(s.violations[0]).toContain(msg);
        expect(s.cashByCurrency).toEqual({ EUR: 1000, USD: 0 });
    });

    it('fx without enough source balance is rejected', () => {
        const s = computeManualDemoAccount({ EUR: 50, USD: 0 }, [fx({ amountFrom: 100 })]);
        expect(s.violations).toHaveLength(1);
        expect(s.violations[0]).toContain('saldo EUR insuficiente');
        expect(s.cashByCurrency.EUR).toBe(50);
    });

    it('positions are sorted by instrumentKey and carry the last fill name', () => {
        const ACS: Instrument = { kind: 'accion', symbol: 'ACS', name: 'ACS' };
        const s = computeManualDemoAccount({ EUR: 10_000, USD: 0 }, [
            buy({ instrument: SAN, quantity: 1, price: 4 }),
            buy({ instrument: ACS, quantity: 2, price: 30 }),
        ]);
        expect(s.positions.map((p) => p.instrumentKey)).toEqual(['A:ACS', 'A:SAN']);
        expect(s.positions[1].name).toBe('Banco Santander');
    });

    it('realized pnl accumulates across round trips in the same book', () => {
        const s = computeManualDemoAccount({ EUR: 10_000, USD: 0 }, [
            buy({ quantity: 10, price: 4 }),
            sell({ quantity: 10, price: 6 }), // +20
            buy({ quantity: 10, price: 5 }),
            sell({ quantity: 10, price: 4 }), // -10
        ]);
        expect(s.realizedPnlByCurrency.EUR).toBe(10);
        expect(s.positions).toEqual([]);
        expect(s.violations).toEqual([]);
    });
});
