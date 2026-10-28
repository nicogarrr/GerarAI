import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, getCandles } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    getCandles: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getCandles }));

import { runWalkForwardBacktest } from '@/lib/actions/propicks-backtest.actions';

/** Replica los cortes del módulo (fines de mes UTC) para construir velas que los cubran. */
function cutoffsFor(months: number): Date[] {
    const now = new Date();
    const baseY = now.getUTCFullYear();
    const baseM = now.getUTCMonth();
    const cutoffs: Date[] = [];
    for (let i = 0; i <= months; i++) {
        cutoffs.push(new Date(Date.UTC(baseY, baseM - (months - i) + 1, 0, 23, 59, 59)));
    }
    return cutoffs;
}

/** Serie diaria artificial: path(i) da el cierre del día i entre from y to. */
function series(fromSec: number, toSec: number, path: (dayIndex: number, total: number) => number) {
    const t: number[] = [];
    const c: number[] = [];
    const total = Math.floor((toSec - fromSec) / 86400) + 1;
    for (let sec = fromSec, i = 0; sec <= toSec; sec += 86400, i++) {
        t.push(sec);
        c.push(path(i, total));
    }
    return { s: 'ok', t, c };
}

/** Monta getCandles: AAPL sube siempre; el resto plano; SPY plano. Extra: overrides por símbolo. */
function seedCandles(months: number, overrides: Record<string, (i: number, total: number) => number> = {}) {
    const cuts = cutoffsFor(months);
    const from = Math.floor(cuts[0].getTime() / 1000) - 420 * 86400;
    const to = Math.floor(cuts[months].getTime() / 1000) + 86400;
    const total = Math.floor((to - from) / 86400) + 1;
    getCandles.mockImplementation(async (symbol: string) => {
        const path = overrides[symbol] ?? (symbol === 'AAPL' ? (i: number) => 100 + i * 0.1 : () => 100);
        return series(from, to, path);
    });
    return { cuts, from, to, total };
}

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
});

describe('runWalkForwardBacktest', () => {
    it('exige sesión y nunca lanza: devuelve { error }', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('No autenticado'));
        expect(await runWalkForwardBacktest()).toEqual({ error: 'No autenticado' });
        expect(getCandles).not.toHaveBeenCalled();
    });

    it('sin datos de mercado -> error honesto', async () => {
        getCandles.mockResolvedValue(null);
        expect(await runWalkForwardBacktest({ months: 1 })).toEqual({
            error: 'No hay datos de mercado suficientes para el backtest walk-forward',
        });
    });

    it('selecciona el símbolo con mejor momentum y cobra costes de rotación', async () => {
        seedCandles(1);
        const result = await runWalkForwardBacktest({ months: 1, topN: 1 });
        expect(result).not.toHaveProperty('error');
        if ('error' in result) return;
        expect(result.months).toBe(1);
        const mes = result.tablaMensual[0];
        expect(mes.picks).toEqual(['AAPL']);
        expect(mes.turnover).toBe(100); // primer mes: cartera entera nueva
        expect(mes.retBruto).toBeGreaterThan(0);
        // coste = 2 patas x 15pb con rotación total
        expect(mes.retNeto).toBeCloseTo(mes.retBruto - 0.3, 2);
        expect(mes.spy).toBe(0); // SPY plano
        expect(result.maxDD).toBeLessThanOrEqual(0);
        expect(result.snapshots).toHaveLength(1);
        expect(result.snapshots[0].symbols).toEqual(['AAPL']);
    });

    it('PROHIBIDO mirar el futuro: una subida entre cortes no influye en la selección', async () => {
        seedCandles(1, {
            // NVDA plano hasta después del corte de selección, luego x10:
            // si la selección usara datos futuros, NVDA sería el pick.
            NVDA: (i, total) => (i < total - 10 ? 100 : 1000),
        });
        const result = await runWalkForwardBacktest({ months: 1, topN: 1 });
        if ('error' in result) throw new Error('no debería fallar');
        expect(result.tablaMensual[0].picks).toEqual(['AAPL']);
    });

    it('meses y topN se acotan (0 -> 1, 5000 -> 36; topN 0 -> 1)', async () => {
        seedCandles(36);
        const clamped = await runWalkForwardBacktest({ months: 5000, topN: 0 });
        if ('error' in clamped) throw new Error('no debería fallar');
        expect(clamped.months).toBe(36);
        expect(clamped.tablaMensual.every((m) => m.picks.length === 1)).toBe(true);
    });

    it('rotación 0 % cuando los picks no cambian entre meses', async () => {
        seedCandles(2);
        const result = await runWalkForwardBacktest({ months: 2, topN: 1 });
        if ('error' in result) throw new Error('no debería fallar');
        expect(result.tablaMensual[0].turnover).toBe(100);
        expect(result.tablaMensual[1].turnover).toBe(0);
        // sin rotación, neto = bruto
        expect(result.tablaMensual[1].retNeto).toBeCloseTo(result.tablaMensual[1].retBruto, 2);
    });

    it('un símbolo sin 253 sesiones antes del corte no es elegible', async () => {
        const { to, total } = seedCandles(1);
        // MSFT: solo 100 velas al final (IPO reciente): aunque sube, no puede ser pick.
        getCandles.mockImplementation(async (symbol: string) => {
            if (symbol === 'MSFT') {
                const t: number[] = [];
                const c: number[] = [];
                for (let i = 0; i < 100; i++) {
                    t.push(to - (99 - i) * 86400);
                    c.push(100 + i); // sube mucho
                }
                return { s: 'ok', t, c };
            }
            if (symbol === 'AAPL') return series(to - (total - 1) * 86400, to, (i) => 100 + i * 0.1);
            return series(to - (total - 1) * 86400, to, () => 100);
        });
        const result = await runWalkForwardBacktest({ months: 1, topN: 2 });
        if ('error' in result) throw new Error('no debería fallar');
        expect(result.tablaMensual[0].picks).not.toContain('MSFT');
    });

    it('velas con s distinto de "ok" se ignoran', async () => {
        seedCandles(1);
        getCandles.mockImplementation(async (symbol: string) => {
            if (symbol === 'AAPL') return { s: 'no_data', t: [], c: [] };
            return null;
        });
        expect(await runWalkForwardBacktest({ months: 1 })).toEqual({
            error: 'No hay datos de mercado suficientes para el backtest walk-forward',
        });
    });
});
