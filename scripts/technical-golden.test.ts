/**
 * Tests dorados y de propiedades de los indicadores técnicos de lib/market
 * (auditoría de fórmulas, fase 2). Llaman a las funciones reales.
 * Los casos aleatorios usan un generador con semilla fija (LCG), así que son
 * deterministas y no añaden dependencias.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error Node type stripping requires the extension.
import { adx, dailyPivots, fibonacci, sma } from '../lib/market/technical.ts';
// @ts-expect-error Node type stripping requires the extension.
import { summarizeCandles } from '../lib/market/candles.ts';

type Bar = { date: string; open: number; high: number; low: number; close: number; volume: number | null };

/** Generador congruencial (Numerical Recipes) con semilla fija: reproducible. */
function lcg(seed: number): () => number {
    let state = seed >>> 0;
    return () => {
        state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
        return state / 2 ** 32;
    };
}

function day(i: number): string {
    return new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10);
}

function randomBars(rand: () => number, n: number): Bar[] {
    let close = 50 + rand() * 100;
    const out: Bar[] = [];
    for (let i = 0; i < n; i++) {
        const open = close;
        close = Math.max(1, close * (1 + (rand() - 0.5) * 0.08));
        const high = Math.max(open, close) * (1 + rand() * 0.03);
        const low = Math.min(open, close) * (1 - rand() * 0.03);
        out.push({ date: day(i), open, high, low, close, volume: null });
    }
    return out;
}

const close = (a: number, b: number, eps = 1e-9) => Math.abs(a - b) <= eps * Math.max(1, Math.abs(b));

test('pivotes clásicos: H 110, L 90, C 100 → P 100; R1 110, S1 90, R2 120, S2 80 (Investopedia «Pivot Point»)', () => {
    const levels = dailyPivots([{ date: '2026-01-02', open: 95, high: 110, low: 90, close: 100, volume: null }]);
    assert.deepEqual(
        levels.map((l: { label: string; price: number }) => [l.label, l.price]),
        [['R2', 120], ['R1', 110], ['S1', 90], ['S2', 80]],
    );
});

test('SMA = media de los n últimos cierres (Murphy, 1999): cierres 1..10, n = 4 → (7+8+9+10)/4 = 8,5', () => {
    const bars = Array.from({ length: 10 }, (_, i) => ({ date: day(i), close: i + 1, volume: null }));
    assert.equal(sma(bars, 4), 8.5);
    assert.equal(sma(bars, 11), null);
});

test('Fibonacci: H − (H − L)·r sobre el rango visible; L 90, H 110, r 0,618 → 97,64', () => {
    const bars = [
        { date: day(0), open: 95, high: 100, low: 90, close: 98, volume: null },
        { date: day(1), open: 98, high: 110, low: 97, close: 105, volume: null },
    ];
    const level = fibonacci(bars).find((l: { ratio: number }) => l.ratio === 0.618);
    assert.ok(level);
    assert.ok(close(level.price, 110 - 20 * 0.618));
});

test('variación del periodo: (último − primero)/|primero|·100; 100 → 105 = +5 %', () => {
    const summary = summarizeCandles([
        { time: day(0), open: 100, high: 101, low: 99, close: 100, volume: null },
        { time: day(1), open: 100, high: 106, low: 100, close: 105, volume: 10 },
    ]);
    assert.ok(summary);
    assert.notEqual(summary.changePercent, null);
    assert.ok(close(summary.changePercent as number, 5));
    assert.equal(summary.knownVolumeSessions, 1);
});

test('propiedad: la SMA de una serie constante es la constante y siempre queda entre mínimo y máximo (200 casos)', () => {
    const rand = lcg(401);
    for (let k = 0; k < 200; k++) {
        const n = 1 + Math.floor(rand() * 60);
        const c = 0.5 + rand() * 1000;
        const flat = Array.from({ length: n }, (_, i) => ({ date: day(i), close: c, volume: null }));
        const period = 1 + Math.floor(rand() * n);
        assert.ok(close(sma(flat, period) as number, c));
        const bars = randomBars(rand, n);
        const value = sma(bars, period) as number;
        const window = bars.slice(-period).map((b) => b.close);
        assert.ok(value >= Math.min(...window) - 1e-9 && value <= Math.max(...window) + 1e-9);
    }
});

test('propiedad: el ADX de Wilder queda en [0, 100] y no cambia al escalar todos los precios (200 casos)', () => {
    const rand = lcg(402);
    for (let k = 0; k < 200; k++) {
        const bars = randomBars(rand, 28 + Math.floor(rand() * 80));
        const value = adx(bars);
        assert.ok(value !== null && value >= 0 && value <= 100, `ADX fuera de rango: ${value}`);
        const factor = 0.1 + rand() * 20;
        const scaled = bars.map((b) => ({ ...b, open: b.open * factor, high: b.high * factor, low: b.low * factor, close: b.close * factor }));
        assert.ok(close(adx(scaled) as number, value, 1e-6));
    }
});

test('propiedad: pivotes ordenados S2 ≤ S1 ≤ R1 ≤ R2 y niveles de Fibonacci dentro del rango (200 casos)', () => {
    const rand = lcg(403);
    for (let k = 0; k < 200; k++) {
        const bars = randomBars(rand, 2 + Math.floor(rand() * 40));
        const levels = Object.fromEntries(dailyPivots(bars).map((l: { label: string; price: number }) => [l.label, l.price]));
        if ('S2' in levels) assert.ok(levels.S2 <= levels.S1 + 1e-9);
        assert.ok(levels.S1 <= levels.R1 + 1e-9 && levels.R1 <= levels.R2 + 1e-9);
        const low = Math.min(...bars.map((b) => b.low));
        const high = Math.max(...bars.map((b) => b.high));
        for (const level of fibonacci(bars)) assert.ok(level.price >= low && level.price <= high);
    }
});
