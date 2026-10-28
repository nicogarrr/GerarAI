// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { computeManualDemoAccount } from '@/lib/paper-trading/accounting';
import type { Fill, FxConversion, Instrument } from '@/lib/paper-trading/types';

const SAN: Instrument = { kind: 'accion', symbol: 'SAN', name: 'Banco Santander' };
const CALL: Instrument = {
    kind: 'opcion',
    contract: { underlying: 'AAPL', callPut: 'call', strike: 200, expiry: '2026-12-18', multiplier: 100, deliverable: 'acciones', adjusted: false },
    name: 'AAPL 2026-12-18 200 Call',
};

let seq = 0;
function fill(patch: Partial<Fill>): Fill {
    seq += 1;
    return {
        instrument: SAN, side: 'buy', openClose: 'open', quantity: 10, price: 4,
        currency: 'EUR', fee: 0, executedAt: 1_700_000_000_000 + seq * 1000,
        source: 'manual-simulado', clientOrderId: `ord-${seq}`, ...patch,
    };
}
function fx(patch: Partial<FxConversion>): FxConversion {
    seq += 1;
    return {
        kind: 'fx', from: 'EUR', to: 'USD', amountFrom: 100, rate: 1.1,
        executedAt: 1_700_000_000_000 + seq * 1000, source: 'manual-simulado',
        clientOrderId: `fx-${seq}`, ...patch,
    };
}

describe('computeManualDemoAccount - cash y posiciones', () => {
    it('sin movimientos devuelve el saldo inicial y ninguna posición', () => {
        const state = computeManualDemoAccount({ EUR: 100_000, USD: 0 }, []);
        expect(state.cashByCurrency).toEqual({ EUR: 100_000, USD: 0 });
        expect(state.positions).toEqual([]);
        expect(state.violations).toEqual([]);
        expect(state.realizedPnlByCurrency).toEqual({ EUR: 0, USD: 0 });
    });

    it('una compra descuenta importe + comisión y abre posición con coste medio', () => {
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fill({ quantity: 10, price: 4, fee: 5 })]);
        expect(state.cashByCurrency.EUR).toBe(955);
        expect(state.positions).toHaveLength(1);
        expect(state.positions[0]).toMatchObject({ instrumentKey: 'A:SAN', quantity: 10, avgCost: 4, realizedPnl: 0, currency: 'EUR', kind: 'accion' });
    });

    it('una venta cierra lotes FIFO y calcula la PyG realizada por divisa', () => {
        const state = computeManualDemoAccount({ EUR: 10_000, USD: 0 }, [
            fill({ quantity: 10, price: 4 }),
            fill({ quantity: 10, price: 5 }),
            fill({ side: 'sell', openClose: 'close', quantity: 15, price: 6 }),
        ]);
        // PyG: 10*(6-4) + 5*(6-5) = 25; quedan 5 acciones a coste 5.
        expect(state.realizedPnlByCurrency.EUR).toBe(25);
        expect(state.positions).toHaveLength(1);
        expect(state.positions[0]).toMatchObject({ quantity: 5, avgCost: 5, realizedPnl: 25 });
        // Cash: 10000 - 40 - 50 + 90 = 10000.
        expect(state.cashByCurrency.EUR).toBe(10_000);
    });

    it('una venta con comisión la descuenta del cash abonado', () => {
        const state = computeManualDemoAccount({ EUR: 100, USD: 0 }, [
            fill({ quantity: 10, price: 9, fee: 10 }),
            fill({ side: 'sell', openClose: 'close', quantity: 10, price: 9, fee: 5 }),
        ]);
        expect(state.cashByCurrency.EUR).toBe(85);
        expect(state.positions).toEqual([]);
    });
});

describe('computeManualDemoAccount - defensa del libro (violations)', () => {
    it('una compra sin saldo no se aplica y queda en violations', () => {
        const state = computeManualDemoAccount({ EUR: 50, USD: 0 }, [fill({ quantity: 100, price: 4 })]);
        expect(state.cashByCurrency.EUR).toBe(50);
        expect(state.positions).toEqual([]);
        expect(state.violations).toHaveLength(1);
        expect(state.violations[0]).toContain('saldo EUR insuficiente');
    });

    it('una sobreventa se rechaza entera: ni cash ni lotes se mueven', () => {
        const state = computeManualDemoAccount({ EUR: 10_000, USD: 0 }, [
            fill({ quantity: 10, price: 4 }),
            fill({ side: 'sell', openClose: 'close', quantity: 25, price: 6 }),
        ]);
        expect(state.cashByCurrency.EUR).toBe(9_960);
        expect(state.positions[0]).toMatchObject({ quantity: 10, avgCost: 4 });
        expect(state.violations[0]).toContain('pedida x25, posición x10');
    });

    it('una venta cuya comisión no cabe tras abonar el importe se rechaza entera', () => {
        const state = computeManualDemoAccount({ EUR: 50, USD: 0 }, [
            fill({ quantity: 5, price: 9, fee: 5 }),
            fill({ side: 'sell', openClose: 'close', quantity: 5, price: 1, fee: 10 }),
        ]);
        expect(state.cashByCurrency.EUR).toBe(0);
        expect(state.positions[0]).toMatchObject({ quantity: 5, avgCost: 9 });
        expect(state.violations[0]).toContain('comisión 10 supera el efectivo disponible');
    });

    it('EUR y USD NO se cruzan en el mismo FIFO aunque sea el mismo símbolo', () => {
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [
            fill({ quantity: 10, price: 4, currency: 'EUR' }),
            fill({ side: 'sell', openClose: 'close', quantity: 5, price: 4, currency: 'USD' }),
        ]);
        expect(state.positions).toHaveLength(1);
        expect(state.positions[0].currency).toBe('EUR');
        expect(state.violations[0]).toContain('USD|A:SAN');
    });
});

describe('computeManualDemoAccount - ordenación FIFO', () => {
    it('ordena por executedAt aunque el array llegue desordenado', () => {
        const buy = fill({ quantity: 10, price: 4, executedAt: 1_000 });
        const sell = fill({ side: 'sell', openClose: 'close', quantity: 5, price: 6, executedAt: 2_000 });
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [sell, buy]);
        expect(state.violations).toEqual([]);
        expect(state.realizedPnlByCurrency.EUR).toBe(10);
        expect(state.positions[0].quantity).toBe(5);
    });

    it('desempata executedAt iguales por tiebreak, no por el orden del array', () => {
        // Dos compras al mismo instante: el tiebreak menor es el lote más antiguo.
        const barato = fill({ quantity: 5, price: 4, executedAt: 1_000, tiebreak: 10 });
        const caro = fill({ quantity: 5, price: 8, executedAt: 1_000, tiebreak: 20 });
        const sell = fill({ side: 'sell', openClose: 'close', quantity: 5, price: 10, executedAt: 2_000 });
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [caro, sell, barato]);
        // FIFO real: cierra el lote de 4 (tiebreak 10), no el de 8.
        expect(state.realizedPnlByCurrency.EUR).toBe(30);
        expect(state.positions[0]).toMatchObject({ quantity: 5, avgCost: 8 });
    });
});

describe('computeManualDemoAccount - conversión fx manual', () => {
    it('mueve saldo entre divisas aplicando el tipo introducido', () => {
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx({ amountFrom: 100, rate: 1.1 })]);
        expect(state.cashByCurrency).toEqual({ EUR: 900, USD: 110 });
        expect(state.violations).toEqual([]);
    });

    it('rechaza convertir una divisa en sí misma (crearía dinero)', () => {
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx({ from: 'EUR', to: 'EUR' })]);
        expect(state.cashByCurrency.EUR).toBe(1000);
        expect(state.violations[0]).toContain('divisa origen y destino iguales');
    });

    it.each([
        ['importe 0', { amountFrom: 0 }],
        ['importe negativo', { amountFrom: -5 }],
        ['importe NaN', { amountFrom: NaN }],
        ['tipo 0', { rate: 0 }],
        ['tipo negativo', { rate: -1.2 }],
        ['tipo NaN', { rate: NaN }],
    ])('rechaza fx con %s', (_etiqueta, patch) => {
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx(patch)]);
        expect(state.cashByCurrency).toEqual({ EUR: 1000, USD: 0 });
        expect(state.violations[0]).toContain('importe o tipo inválido');
    });

    it('rechaza fx sin saldo suficiente en la divisa origen', () => {
        const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [fx({ amountFrom: 2000 })]);
        expect(state.cashByCurrency).toEqual({ EUR: 1000, USD: 0 });
        expect(state.violations[0]).toContain('saldo EUR insuficiente');
    });
});

describe('computeManualDemoAccount - opciones (multiplicador 100)', () => {
    it('la prima se multiplica por 100 al comprar y la PyG al cerrar', () => {
        const state = computeManualDemoAccount({ EUR: 0, USD: 10_000 }, [
            fill({ instrument: CALL, quantity: 1, price: 2, currency: 'USD', fee: 1 }),
            fill({ instrument: CALL, side: 'sell', openClose: 'close', quantity: 1, price: 3, currency: 'USD', fee: 1 }),
        ]);
        // Compra: -(2*100 + 1) = -201. Venta: +(3*100 - 1) = +299.
        expect(state.cashByCurrency.USD).toBe(10_000 - 201 + 299);
        expect(state.realizedPnlByCurrency.USD).toBe(100);
        expect(state.positions).toEqual([]);
    });

    it('una posición de opción abierta muestra coste medio por acción (sin multiplicador)', () => {
        const state = computeManualDemoAccount({ EUR: 0, USD: 10_000 }, [
            fill({ instrument: CALL, quantity: 2, price: 2, currency: 'USD' }),
        ]);
        expect(state.positions[0]).toMatchObject({ kind: 'opcion', quantity: 2, avgCost: 2, name: 'AAPL 2026-12-18 200 Call' });
        expect(state.positions[0].instrumentKey).toBe('O:AAPL:2026-12-18:call:200:100');
    });
});

describe('computeManualDemoAccount - presentación de posiciones', () => {
    it('ordena las posiciones por instrumentKey y no inventa posiciones cerradas', () => {
        const state = computeManualDemoAccount({ EUR: 100_000, USD: 0 }, [
            fill({ instrument: { kind: 'accion', symbol: 'ZZZ', name: 'Zeta' }, quantity: 1, price: 10 }),
            fill({ instrument: SAN, quantity: 1, price: 10 }),
            fill({ instrument: SAN, side: 'sell', openClose: 'close', quantity: 1, price: 10 }),
        ]);
        expect(state.positions.map((p) => p.instrumentKey)).toEqual(['A:ZZZ']);
    });
});
