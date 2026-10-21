/**
 * GUARDS PERMANENTES de invariantes de la demo manual de paper trading.
 * Independiente de scripts/paper-trading-accounting.test.ts: aquí viven las
 * propiedades que NUNCA pueden romperse, vengan de donde vengan los datos.
 *
 * Decisiones horneadas (coordinación auditoría 2026-10-21):
 * - Sobreventa: RECHAZO TOTAL. Sin orden parcial explícita en UI no se
 *   aplica nada: ni cash ni cierre parcial; queda violation.
 * - FX misma divisa (EUR->EUR) no existe: violation, cash intacto.
 * - La divisa forma parte de la identidad del instrumento en el libro:
 *   una venta en USD no cierra un lote comprado en EUR.
 * - El libro es invariante al orden de llegada: manda executedAt.
 *
 * NOTA DE SECUENCIA: sobre el head 1a5b4d91 los tests 'sobreventa rechazo
 * total', 'fx misma divisa' y 'divisa en la clave FIFO' fallan EN ROJO a
 * propósito (el fix va en el commit siguiente del pilot). Mergear este
 * archivo junto con ese fix o después, nunca antes: run-guards descubre
 * scripts/*.test.ts automáticamente.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). Mismo patron que los guards existentes.
import { computeManualDemoAccount } from '../lib/paper-trading/accounting.ts';
// @ts-expect-error -- mismo motivo
import { toFill, type Fill, type FxConversion, type LedgerEntry } from '../lib/paper-trading/types.ts';

const accion = (symbol: string) => ({ kind: 'accion' as const, symbol, name: symbol });

let n = 0;
const fill = (
    symbol: string,
    side: 'buy' | 'sell',
    quantity: number,
    price: number,
    executedAt: number,
    currency: 'EUR' | 'USD' = 'EUR',
    fee = 0
): Fill => {
    const f = toFill({
        instrument: accion(symbol),
        side,
        openClose: side === 'buy' ? 'open' : 'close',
        quantity,
        price,
        currency,
        fee,
        executedAt,
        clientOrderId: `g${++n}`,
    });
    assert.ok(f, 'fill de test válido');
    return f;
};

const fx = (from: 'EUR' | 'USD', to: 'EUR' | 'USD', amountFrom: number, rate: number, executedAt: number): FxConversion => ({
    kind: 'fx',
    from,
    to,
    amountFrom,
    rate,
    executedAt,
    source: 'manual-simulado',
    clientOrderId: `fx${++n}`,
});

/** PRNG con semilla: los property tests deben ser deterministas. */
const mulberry32 = (seed: number) => () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

test('INVARIANTE sobreventa: rechazo total — ni cash ni cierre parcial sin contrato de orden parcial', () => {
    const state = computeManualDemoAccount({ EUR: 10, USD: 0 }, [
        fill('Y', 'buy', 1, 10, 100),
        fill('Y', 'sell', 5, 20, 200), // pedida x5, posición x1: NO se ejecuta nada
    ]);
    assert.equal(state.cashByCurrency.EUR, 0, 'la sobreventa no abona ni un euro');
    assert.equal(state.positions.length, 1, 'la posición sigue entera');
    assert.equal(state.positions[0].quantity, 1);
    assert.equal(state.realizedPnlByCurrency.EUR, 0);
    assert.ok(state.violations.length > 0, 'la sobreventa deja violation visible');
});

test('INVARIANTE vender sin tener: jamás sale dinero de la nada', () => {
    const state = computeManualDemoAccount({ EUR: 0, USD: 0 }, [
        fill('Z', 'sell', 3, 50, 100),
        fill('Z', 'sell', 1, 10, 200),
    ]);
    assert.equal(state.cashByCurrency.EUR, 0);
    assert.equal(state.cashByCurrency.USD, 0);
    assert.equal(state.positions.length, 0);
    assert.equal(state.violations.length, 2);
});

test('INVARIANTE fx misma divisa: no existe, no crea dinero', () => {
    const state = computeManualDemoAccount({ EUR: 1000, USD: 500 }, [
        fx('EUR', 'EUR', 100, 2, 100),
        fx('USD', 'USD', 50, 0.5, 200),
    ]);
    assert.equal(state.cashByCurrency.EUR, 1000);
    assert.equal(state.cashByCurrency.USD, 500);
    assert.equal(state.violations.length, 2);
});

test('INVARIANTE divisa en la identidad del instrumento: una venta USD no cierra un lote EUR', () => {
    const state = computeManualDemoAccount({ EUR: 1000, USD: 0 }, [
        fill('SAN', 'buy', 10, 10, 100, 'EUR'),
        fill('SAN', 'sell', 10, 12, 200, 'USD'), // sin posición USD: rechazo total
    ]);
    assert.equal(state.cashByCurrency.EUR, 900);
    assert.equal(state.cashByCurrency.USD, 0, 'ninguna venta USD casa con lotes EUR');
    assert.equal(state.positions.length, 1);
    assert.equal(state.positions[0].quantity, 10);
    assert.ok(state.violations.length > 0);
});

test('PROPIEDAD orden-invariancia: executedAt distinto => cualquier baraja da el mismo libro', () => {
    const rand = mulberry32(42);
    const base: LedgerEntry[] = [
        fill('A', 'buy', 10, 10, 1),
        fill('A', 'buy', 10, 20, 2),
        fill('B', 'buy', 5, 50, 3),
        fill('A', 'sell', 15, 30, 4, 'EUR', 1),
        fx('EUR', 'USD', 100, 1.1, 5),
        fill('C', 'buy', 1, 10, 6, 'USD'),
        fill('B', 'sell', 3, 60, 7),
        fill('A', 'buy', 3, 25, 8),
    ];
    const normalize = (s: ReturnType<typeof computeManualDemoAccount>) =>
        JSON.stringify({ ...s, violations: [...s.violations].sort() });
    const reference = normalize(computeManualDemoAccount({ EUR: 5000, USD: 0 }, base));
    for (let i = 0; i < 100; i++) {
        const shuffled = [...base];
        for (let j = shuffled.length - 1; j > 0; j--) {
            const k = Math.floor(rand() * (j + 1));
            [shuffled[j], shuffled[k]] = [shuffled[k], shuffled[j]];
        }
        assert.equal(normalize(computeManualDemoAccount({ EUR: 5000, USD: 0 }, shuffled)), reference, `baraja ${i} diverge`);
    }
});

test('PROPIEDAD sanidad aleatoria: estados siempre finitos, posiciones nunca negativas (semilla fija)', () => {
    const rand = mulberry32(20261021);
    for (let seq = 0; seq < 200; seq++) {
        const entries: LedgerEntry[] = [];
        let t = 1;
        for (let j = 0; j < 20; j++) {
            const r = rand();
            const symbol = `S${j % 3}`;
            const currency = rand() < 0.7 ? 'EUR' : 'USD';
            if (r < 0.4) {
                entries.push(fill(symbol, 'buy', 1 + Math.floor(rand() * 10), 1 + rand() * 100, t++, currency, rand() < 0.3 ? 1 : 0));
            } else if (r < 0.85) {
                entries.push(fill(symbol, 'sell', 1 + Math.floor(rand() * 15), 1 + rand() * 100, t++, currency, rand() < 0.3 ? 1 : 0));
            } else {
                entries.push(fx('EUR', 'USD', Math.floor(rand() * 500), 1 + rand(), t++));
            }
        }
        const state = computeManualDemoAccount({ EUR: 10000, USD: 1000 }, entries);
        assert.ok(Number.isFinite(state.cashByCurrency.EUR), `seq ${seq}: EUR no finito`);
        assert.ok(Number.isFinite(state.cashByCurrency.USD), `seq ${seq}: USD no finito`);
        assert.ok(Number.isFinite(state.realizedPnlByCurrency.EUR) && Number.isFinite(state.realizedPnlByCurrency.USD), `seq ${seq}: realizado no finito`);
        for (const p of state.positions) {
            assert.ok(p.quantity > 0 && Number.isInteger(p.quantity), `seq ${seq}: cantidad inválida ${p.quantity}`);
            assert.ok(Number.isFinite(p.avgCost) && p.avgCost > 0, `seq ${seq}: avgCost inválido`);
            assert.ok(Number.isFinite(p.realizedPnl), `seq ${seq}: realizedPnl inválido`);
        }
    }
});
