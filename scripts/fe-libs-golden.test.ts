/**
 * Golden y propiedades de las librerías de frontend que la auditoría de
 * fórmulas no cubría: ProPicks (estrategias y validador), demo manual
 * (FIFO y opciones), cartera (resumen, histórico, reparto, caja, G/P nativa)
 * y plan (objetivos por dimensión).
 *
 * Cada golden llama a la función real con números redondos; el comentario
 * dice de dónde sale la cifra esperada, calculada a mano.
 * Las propiedades usan un generador con semilla fija (200 casos cada una).
 *
 * Ejecución: node --experimental-strip-types --test scripts/fe-libs-golden.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { calculateStrategyScore, passesStrategyFilters, getStrategyById, PROPICKS_STRATEGIES } from '../lib/utils/proPicksStrategies.ts';
// @ts-expect-error TS5097
import { validateScoreFormula, validateNumbersTraceable, PROPICKS_SCORING_WEIGHTS } from '../lib/utils/propicksValidation.ts';
// @ts-expect-error TS5097
import { computeManualDemoAccount } from '../lib/paper-trading/accounting.ts';
// @ts-expect-error TS5097
import { premiumTotal, optionCashDelta, intrinsicValue } from '../lib/paper-trading/options.ts';
// @ts-expect-error TS5097
import { buildPortfolioInsight } from '../lib/portfolio-insight.ts';
// @ts-expect-error TS5097
import { verifiedPortfolioHistory } from '../lib/portfolio-history.ts';
// @ts-expect-error TS5097
import { buildAllocationSlices } from '../lib/portfolio-allocation.ts';
// @ts-expect-error TS5097
import { sumCashByCurrency } from '../lib/portfolio-cash.ts';
// @ts-expect-error TS5097
import { nativePnlIfContradicts } from '../lib/portfolio-native-pnl.ts';
// @ts-expect-error TS5097
import { moatChecksToScore } from '../lib/propicks/moat-scale.ts';
// @ts-expect-error TS5097
import { overallocatedDimension } from '../lib/plan/target-totals.ts';

type Cats = { value: number; growth: number; profitability: number; cashFlow: number; momentum: number; debtLiquidity: number };
const CATS: Cats = { value: 80, growth: 60, profitability: 40, cashFlow: 100, momentum: 20, debtLiquidity: 60 };
const scoreData = (categoryScores: Cats, overallScore = 70) => ({ categoryScores, overallScore }) as never;

// LCG determinista (misma secuencia en cada ejecución).
function rng(seed: number) {
    let s = seed;
    return () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
}

describe('ProPicks: score por estrategia (lib/utils/proPicksStrategies.ts)', () => {
    it('golden: Σ categoría × peso, redondeado', () => {
        // adaptativa: 80·0,20 + 60·0,20 + 40·0,20 + 100·0,15 + 20·0,15 + 60·0,10 = 16+12+8+15+3+6 = 60
        // value:      80·0,35 + 60·0,05 + 40·0,25 + 100·0,15 + 20·0,05 + 60·0,15 = 28+3+10+15+1+9 = 66
        // momentum:   80·0,10 + 60·0,25 + 40·0,15 + 100·0,10 + 20·0,40 + 60·0    = 8+15+6+10+8+0 = 47
        // defensiva:  80·0,15 + 60·0,05 + 40·0,30 + 100·0,20 + 20·0,05 + 60·0,25 = 12+3+12+20+1+15 = 63
        const expected: Record<string, number> = { adaptive: 60, value: 66, momentum: 47, defensiva: 63 };
        for (const strategy of PROPICKS_STRATEGIES) {
            assert.equal(calculateStrategyScore(scoreData(CATS), strategy), expected[strategy.id], strategy.id);
        }
    });

    it('golden: el filtro minScore mira el score GENERAL (60 pasa, 59 no en la adaptativa)', () => {
        const adaptive = getStrategyById('adaptive');
        assert.ok(adaptive);
        assert.equal(passesStrategyFilters(scoreData(CATS, 60), adaptive), true);
        assert.equal(passesStrategyFilters(scoreData(CATS, 59), adaptive), false);
    });

    it('propiedad: pesos que suman 1 → categorías iguales a c dan score c, y siempre en [0, 100]', () => {
        const rand = rng(11);
        for (let k = 0; k < 200; k++) {
            const c = Math.floor(rand() * 101);
            const flat: Cats = { value: c, growth: c, profitability: c, cashFlow: c, momentum: c, debtLiquidity: c };
            const mixed: Cats = {
                value: rand() * 100, growth: rand() * 100, profitability: rand() * 100,
                cashFlow: rand() * 100, momentum: rand() * 100, debtLiquidity: rand() * 100,
            };
            for (const strategy of PROPICKS_STRATEGIES) {
                assert.equal(calculateStrategyScore(scoreData(flat), strategy), c, `${strategy.id} c=${c}`);
                const s = calculateStrategyScore(scoreData(mixed), strategy);
                assert.ok(s >= 0 && s <= 100, `${strategy.id} ${s}`);
            }
        }
    });
});

describe('ProPicks: validador R3/R4 (lib/utils/propicksValidation.ts)', () => {
    const base = { symbol: 'TEST', asOf: '2026-01-01', facts: {}, confidenceReasons: [] };

    it('golden R4: score general = 80·0,15 + 60·0,20 + 40·0,25 + 100·0,15 + 20·0,10 + 60·0,15 = 60', () => {
        // 12 + 12 + 10 + 15 + 2 + 9 = 60; tolerancia ±1 por redondeo.
        assert.deepEqual(validateScoreFormula({ ...base, score: 60, categoryScores: CATS }), []);
        assert.deepEqual(validateScoreFormula({ ...base, score: 61, categoryScores: CATS }), []);
        assert.equal(validateScoreFormula({ ...base, score: 62, categoryScores: CATS }).length, 1);
    });

    it('golden R3: upside = (125 − 100) / 100 · 100 = 25 % (±0,5)', () => {
        const facts = { price: 100, targetMean: 125 };
        const ok = validateNumbersTraceable({ ...base, facts, score: 0, categoryScores: {}, currentPrice: 100, targetPrice: 125, upsidePotential: 25.4 });
        assert.deepEqual(ok, []);
        const bad = validateNumbersTraceable({ ...base, facts, score: 0, categoryScores: {}, currentPrice: 100, targetPrice: 125, upsidePotential: 26 });
        assert.equal(bad.length, 1);
    });

    it('propiedad: los pesos canónicos suman 1 y R4 acepta round(Σ c·w) para cualquier categoría', () => {
        const total = Object.values(PROPICKS_SCORING_WEIGHTS).reduce((a, b) => a + b, 0);
        assert.ok(Math.abs(total - 1) < 1e-12);
        const rand = rng(12);
        for (let k = 0; k < 200; k++) {
            const c: Cats = {
                value: rand() * 100, growth: rand() * 100, profitability: rand() * 100,
                cashFlow: rand() * 100, momentum: rand() * 100, debtLiquidity: rand() * 100,
            };
            const w = PROPICKS_SCORING_WEIGHTS as Record<keyof Cats, number>;
            const score = Math.round((Object.keys(c) as (keyof Cats)[]).reduce((a, key) => a + c[key] * w[key], 0));
            assert.deepEqual(validateScoreFormula({ ...base, score, categoryScores: c }), []);
        }
    });
});

const acc = (side: 'buy' | 'sell', quantity: number, price: number, fee: number, executedAt: number) => ({
    instrument: { kind: 'accion', symbol: 'SAN', name: 'Santander' },
    side, quantity, price, fee, executedAt, currency: 'EUR', source: 'manual-simulado', clientOrderId: `o${executedAt}`,
}) as never;

describe('Demo manual: FIFO (lib/paper-trading/accounting.ts)', () => {
    it('golden: compra 10@100 y 10@120, vende 15@130 (comisión 1 cada una)', () => {
        // Caja: 10.000 − (1.000 + 1) − (1.200 + 1) + (1.950 − 1) = 9.747.
        // FIFO: 10·(130 − 100) + 5·(130 − 120) = 300 + 50 = 350 realizado (sin comisiones).
        // Quedan 5 del segundo lote: coste medio 120.
        const state = computeManualDemoAccount({ EUR: 10_000, USD: 0 }, [acc('buy', 10, 100, 1, 1), acc('buy', 10, 120, 1, 2), acc('sell', 15, 130, 1, 3)]);
        assert.equal(state.cashByCurrency.EUR, 9747);
        assert.equal(state.realizedPnlByCurrency.EUR, 350);
        assert.equal(state.positions.length, 1);
        assert.equal(state.positions[0].quantity, 5);
        assert.equal(state.positions[0].avgCost, 120);
        assert.deepEqual(state.violations, []);
    });

    it('propiedad: comprar lotes y venderlo todo → realizado = Σ q·(venta − precio) y la caja cuadra', () => {
        const rand = rng(13);
        for (let k = 0; k < 200; k++) {
            const n = 1 + Math.floor(rand() * 5);
            const entries: never[] = [];
            let qty = 0;
            let expectedPnl = 0;
            let cash = 1_000_000;
            const sellPrice = 1 + Math.round(rand() * 20000) / 100;
            for (let i = 0; i < n; i++) {
                const q = 1 + Math.floor(rand() * 50);
                const p = 1 + Math.round(rand() * 20000) / 100;
                const fee = Math.round(rand() * 500) / 100;
                entries.push(acc('buy', q, p, fee, i + 1));
                qty += q;
                expectedPnl += q * (sellPrice - p);
                cash = Math.round((cash - Math.round((q * p + fee) * 100) / 100) * 100) / 100;
            }
            entries.push(acc('sell', qty, sellPrice, 0, n + 1));
            cash = Math.round((cash + Math.round(qty * sellPrice * 100) / 100) * 100) / 100;
            const state = computeManualDemoAccount({ EUR: 1_000_000, USD: 0 }, entries);
            assert.ok(Math.abs(state.realizedPnlByCurrency.EUR - expectedPnl) < 1e-6, `k=${k}`);
            assert.ok(Math.abs(state.cashByCurrency.EUR - cash) < 1e-6, `k=${k}`);
            assert.equal(state.positions.length, 0);
        }
    });
});

describe('Demo manual: opciones (lib/paper-trading/options.ts)', () => {
    const contract = { underlying: 'AAPL', callPut: 'call', strike: 100, expiry: '2030-01-18', deliverable: 'acciones', adjusted: false, multiplier: 100 } as never;

    it('golden: prima 1,2345 × 100 × 3 contratos = 370,35; compra con comisión 1,50 = −371,85', () => {
        assert.equal(premiumTotal(1.2345, 3), 370.35);
        assert.equal(optionCashDelta({ side: 'buy', price: 1.2345, quantity: 3, fee: 1.5, instrument: { kind: 'opcion', contract, name: '' } } as never), -371.85);
        assert.equal(optionCashDelta({ side: 'sell', price: 1.2345, quantity: 3, fee: 1.5, instrument: { kind: 'opcion', contract, name: '' } } as never), 368.85);
    });

    it('golden: intrínseco de call 100 con subyacente a 112,5 = 12,5; el put = 0', () => {
        assert.equal(intrinsicValue(contract, 112.5), 12.5);
        assert.equal(intrinsicValue({ ...(contract as object), callPut: 'put' } as never, 112.5), 0);
        assert.equal(intrinsicValue({ ...(contract as object), callPut: 'put' } as never, 87.5), 12.5);
    });

    it('propiedad: la prima es lineal en contratos y paridad put/call del intrínseco: C − P = S − K', () => {
        const rand = rng(14);
        for (let k = 0; k < 200; k++) {
            const premium = Math.round(rand() * 100000) / 10000;
            const n = 1 + Math.floor(rand() * 20);
            assert.ok(Math.abs(premiumTotal(premium, n) - n * premiumTotal(premium, 1)) < 1e-6);
            const strike = 1 + rand() * 500;
            const s = 1 + rand() * 500;
            const call = intrinsicValue({ ...(contract as object), strike } as never, s);
            const put = intrinsicValue({ ...(contract as object), strike, callPut: 'put' } as never, s);
            assert.ok(call >= 0 && put >= 0);
            assert.ok(Math.abs(call - put - (s - strike)) < 1e-9);
        }
    });
});

describe('Cartera: resumen de una línea (lib/portfolio-insight.ts)', () => {
    it('golden: (100 − 60) / (1.000 + 3.000) = +1 %; la que más se mueve es A (10 %); parcial por C sin coste', () => {
        const insight = buildPortfolioInsight({
            holdings: [
                { symbol: 'A', cost: 1000, gain: 100, gainPercent: 10 },
                { symbol: 'B', cost: 3000, gain: -60, gainPercent: -2 },
                { symbol: 'C', cost: 0, gain: 0, gainPercent: 0 },
            ],
        });
        assert.equal(insight.kind, 'movement');
        if (insight.kind !== 'movement') return;
        assert.equal(insight.totalPercent, 1);
        assert.equal(insight.direction, 'up');
        assert.equal(insight.topSymbol, 'A');
        assert.equal(insight.partial, true);
    });

    it('propiedad: totalPercent = Σ ganancia / Σ coste · 100 de las posiciones con coste', () => {
        const rand = rng(15);
        for (let k = 0; k < 200; k++) {
            const holdings = Array.from({ length: 1 + Math.floor(rand() * 8) }, (_, i) => {
                const cost = 1 + rand() * 10000;
                const gain = (rand() - 0.5) * cost;
                return { symbol: `S${i}`, cost, gain, gainPercent: (gain / cost) * 100 };
            });
            const insight = buildPortfolioInsight({ holdings });
            assert.equal(insight.kind, 'movement');
            if (insight.kind !== 'movement') continue;
            const expected = (holdings.reduce((a, h) => a + h.gain, 0) / holdings.reduce((a, h) => a + h.cost, 0)) * 100;
            assert.ok(Math.abs(insight.totalPercent - expected) < 1e-9);
            const maxAbs = Math.max(...holdings.map((h) => Math.abs(h.gainPercent)));
            assert.equal(Math.abs(insight.topGainPercent), maxAbs);
        }
    });
});

describe('Cartera: histórico verificado (lib/portfolio-history.ts)', () => {
    const row = (snapshot_date: string, total_value_base: number, net_external_flow_base: number, daily_return: number, cumulative_twr: number) =>
        ({ id: 0, portfolio_id: 1, snapshot_date, base_currency: 'EUR', positions_value_base: total_value_base, cash_value_base: 0, total_value_base, pricing_coverage: 1, net_external_flow_base, daily_return, cumulative_twr, source: 'market_refresh', metadata: {} });

    it('golden: el rendimiento del día descuenta la aportación: (1.210 − 100) / 1.000 − 1 = 11 %', () => {
        // Día 3: (1.110 − 0) / 1.210 − 1 = −0,0826446…; TWR = 1,11 · (1 − 0,0826446) − 1 = 0,0182645…
        const r3 = 1110 / 1210 - 1;
        const twr3 = 1.11 * (1 + r3) - 1;
        const history = verifiedPortfolioHistory([
            row('2026-01-01', 1000, 0, 0, 0),
            row('2026-01-02', 1210, 100, 0.11, 0.11),
            row('2026-01-03', 1110, 0, r3, twr3),
        ], 'EUR');
        assert.ok(history);
        assert.equal(history.dates.length, 3);
        assert.ok(Math.abs(history.twr - 0.018264462809917) < 1e-12);
        // Un rendimiento que ignora la aportación ((1.210 / 1.000) − 1 = 21 %) rompe la serie.
        const broken = verifiedPortfolioHistory([row('2026-01-01', 1000, 0, 0, 0), row('2026-01-02', 1210, 100, 0.21, 0.21)], 'EUR');
        assert.equal(broken, undefined);
    });

    it('propiedad: una serie coherente generada al azar se acepta entera y su TWR = Π(1 + r) − 1', () => {
        const rand = rng(16);
        for (let k = 0; k < 200; k++) {
            const n = 2 + Math.floor(rand() * 30);
            const rows = [row('2026-01-01', 1000, 0, 0, 0)];
            let value = 1000;
            let twr = 0;
            for (let i = 1; i < n; i++) {
                const r = (rand() - 0.5) * 0.1;
                const flow = rand() < 0.3 ? Math.round((rand() - 0.3) * 200) : 0;
                const next = value * (1 + r) + flow;
                if (next <= 0) break;
                twr = (1 + twr) * (1 + r) - 1;
                const date = new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10);
                rows.push(row(date, next, flow, (next - flow) / value - 1, twr));
                value = next;
            }
            const history = verifiedPortfolioHistory(rows, 'EUR');
            if (rows.length < 2) continue;
            assert.ok(history, `k=${k}`);
            assert.equal(history.dates.length, rows.length);
            const product = history.daily_returns.reduce((w, r) => w * (1 + r), 1) - 1;
            assert.ok(Math.abs(product - history.twr) < 1e-9);
        }
    });
});

describe('Cartera: reparto, caja y G/P nativa', () => {
    it('golden reparto: 300 / 100 / 600 → 30 % / 10 % / 60 %, ordenado por valor', () => {
        const slices = buildAllocationSlices([
            { symbol: 'A', value: 300, gain: 0, gainPercent: 0 },
            { symbol: 'B', value: 100, gain: 0, gainPercent: 0 },
            { symbol: 'C', value: 600, gain: 0, gainPercent: 0 },
        ]);
        assert.deepEqual(slices.map((s: { symbol: string; percentage: number }) => [s.symbol, s.percentage]), [['C', 60], ['A', 30], ['B', 10]]);
    });

    it('propiedad: con valores positivos el reparto suma 100 %', () => {
        const rand = rng(17);
        for (let k = 0; k < 200; k++) {
            const holdings = Array.from({ length: 1 + Math.floor(rand() * 12) }, (_, i) => ({ symbol: `S${i}`, value: 0.01 + rand() * 1e6, gain: 0, gainPercent: 0 }));
            const total = buildAllocationSlices(holdings).reduce((a: number, s: { percentage: number }) => a + s.percentage, 0);
            assert.ok(Math.abs(total - 100) < 1e-9);
        }
    });

    it('golden caja: 100,5 + 50 = 150,5 (un NaN no suma)', () => {
        assert.equal(sumCashByCurrency({ EUR: 100.5, USD: Number.NaN, GBP: 50 }), 150.5);
        assert.equal(sumCashByCurrency(null), 0);
    });

    it('golden G/P nativa: sube 30 USD sobre 600 de coste (5 %) mientras en EUR pierde 20', () => {
        assert.deepEqual(
            nativePnlIfContradicts({ gain: -20, gainKnown: true, nativeGain: 30, nativeCost: 600, nativeCurrency: 'USD', baseCurrency: 'EUR' }),
            { amount: 30, percent: 5, currency: 'USD' },
        );
        assert.equal(nativePnlIfContradicts({ gain: 20, gainKnown: true, nativeGain: 30, nativeCost: 600, nativeCurrency: 'USD', baseCurrency: 'EUR' }), null);
    });
});

describe('ProPicks foso y plan', () => {
    it('golden foso: 5 de 8 criterios = 62,5; fuera de rango se acota', () => {
        assert.equal(moatChecksToScore(5), 62.5);
        assert.equal(moatChecksToScore(9), 100);
        assert.equal(moatChecksToScore(-1), 0);
        assert.equal(moatChecksToScore(1), 12.5);
    });

    it('golden plan: tickers 60 + 50 = 110 % sobrepasa; sectores 70 + 30 = 100 % no', () => {
        assert.deepEqual(
            overallocatedDimension([
                { kind: 'sector', target_pct: 70 }, { kind: 'sector', target_pct: 30 },
                { kind: 'ticker', target_pct: 60 }, { kind: 'ticker', target_pct: 50 },
            ]),
            { kind: 'ticker', total: 110 },
        );
        assert.equal(overallocatedDimension([{ kind: 'sector', target_pct: 70 }, { kind: 'sector', target_pct: 30 }]), null);
    });
});
