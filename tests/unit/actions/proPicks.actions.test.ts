import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requireAuthenticatedUser, getLatestFunnelPicks, getSignalOverlays } = vi.hoisted(() => ({
    requireAuthenticatedUser: vi.fn(),
    getLatestFunnelPicks: vi.fn(),
    getSignalOverlays: vi.fn(),
}));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/actions/propicks-funnel.actions', () => ({ getLatestFunnelPicks }));
vi.mock('@/lib/utils/propicksSignals', () => ({ getSignalOverlays }));

import {
    attachSignalOverlays,
    generateProPicks,
    generateProPicksForStrategy,
    getAvailableStrategies,
    generateEnhancedProPicksWithRun,
    generateEnhancedProPicks,
    type ProPick,
} from '@/lib/actions/proPicks.actions';
import { getStrategyById } from '@/lib/utils/proPicksStrategies';

const pick = (over: Partial<ProPick> = {}): ProPick => ({
    symbol: 'AAPL',
    company: 'Apple',
    score: 75,
    grade: 'B+',
    categoryScores: { value: 60, growth: 70, profitability: 80, cashFlow: 65, momentum: 55, debtLiquidity: 50 },
    reasons: [],
    confidenceReasons: [],
    confidence: 72,
    confidenceLevel: 'Media',
    asOf: '2026-10-27',
    facts: { return12M: 12 },
    currentPrice: 150,
    sector: 'Technology',
    ...over,
});

const funnel = (picks: ProPick[], extra: object = {}) => ({
    picks, runId: 9, runAsOf: '2026-10-27', universeSize: 500, passedCount: picks.length, ...extra,
});

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    getSignalOverlays.mockResolvedValue([]);
});

describe('getAvailableStrategies', () => {
    it('expone id/nombre/descripción, nunca los pesos internos', async () => {
        const strategies = await getAvailableStrategies();
        expect(strategies.length).toBeGreaterThan(0);
        expect(strategies[0]).toEqual({ id: expect.any(String), name: expect.any(String), description: expect.any(String) });
        expect(strategies[0]).not.toHaveProperty('categoryWeights');
    });
});

describe('generateProPicks: fuente = último run del embudo, no evaluación en vivo', () => {
    it('sin run -> lista vacía', async () => {
        getLatestFunnelPicks.mockResolvedValue(null);
        expect(await generateProPicks()).toEqual([]);
    });

    it('filtra score >= 60, ordena por strategyScore y acota el límite a [1,100]', async () => {
        const low = pick({ symbol: 'LOW', score: 40, categoryScores: { value: 10, growth: 10, profitability: 10, cashFlow: 10, momentum: 10, debtLiquidity: 10 } });
        const mid = pick({ symbol: 'MID', score: 65, categoryScores: { value: 50, growth: 50, profitability: 50, cashFlow: 50, momentum: 50, debtLiquidity: 50 } });
        const top = pick({ symbol: 'TOP', score: 90, categoryScores: { value: 95, growth: 95, profitability: 95, cashFlow: 95, momentum: 95, debtLiquidity: 95 } });
        getLatestFunnelPicks.mockResolvedValue(funnel([low, mid, top]));
        const picks = await generateProPicks(5, 'adaptive');
        expect(picks.map((p) => p.symbol)).toEqual(['TOP', 'MID']);
        expect(picks.every((p) => p.score >= 60)).toBe(true);
        expect(picks[0].strategy).toBe('adaptive');
        expect(picks[0].strategyScore).toBeGreaterThan(picks[1].strategyScore ?? 0);
    });

    it('estrategia desconocida cae en la primera del catálogo', async () => {
        getLatestFunnelPicks.mockResolvedValue(funnel([pick()]));
        const picks = await generateProPicks(5, 'estrategia-inventada');
        expect(picks[0].strategy).toBe('adaptive');
    });

    it('límite 0 y 5000 se acotan a 1 y 100', async () => {
        getLatestFunnelPicks.mockResolvedValue(funnel([pick({ symbol: 'A' }), pick({ symbol: 'B' })]));
        expect(await generateProPicks(0)).toHaveLength(1);
        expect((await generateProPicks(5000)).length).toBeLessThanOrEqual(100);
    });

    it('generateProPicksForStrategy es el mismo pipeline con otra estrategia', async () => {
        getLatestFunnelPicks.mockResolvedValue(funnel([pick()]));
        const dividend = getStrategyById('dividend') ?? undefined;
        const picks = await generateProPicksForStrategy(dividend?.id ?? 'adaptive', 3);
        expect(picks).toHaveLength(1);
    });
});

describe('generateEnhancedProPicksWithRun', () => {
    const tech = pick({ symbol: 'TECH', score: 90, sector: 'Software Technology' });
    const bank = pick({ symbol: 'BANK', score: 85, sector: 'Banks', categoryScores: { value: 95, growth: 30, profitability: 50, cashFlow: 50, momentum: 40, debtLiquidity: 60 } });
    const weak = pick({ symbol: 'WEAK', score: 50 });

    it('filtro por score mínimo y sector con alias; runAsOf/passedCount del run', async () => {
        getLatestFunnelPicks.mockResolvedValue(funnel([tech, bank, weak], { passedCount: 3 }));
        const result = await generateEnhancedProPicksWithRun({ minScore: 70, sector: 'Financial Services' }, { includeSignalOverlays: false });
        expect(result.picks.map((p) => p.symbol)).toEqual(['BANK']);
        expect(result.runAsOf).toBe('2026-10-27');
        expect(result.passedCount).toBe(3);
    });

    it('sin run: runAsOf y passedCount null (la página no inventa la fecha del dato)', async () => {
        getLatestFunnelPicks.mockResolvedValue(null);
        const result = await generateEnhancedProPicksWithRun();
        expect(result).toEqual({ picks: [], runAsOf: null, passedCount: null });
    });

    it('sortBy momentum usa la categoría, no el score global', async () => {
        const momentumKing = pick({ symbol: 'MOM', score: 70, categoryScores: { value: 50, growth: 50, profitability: 50, cashFlow: 50, momentum: 99, debtLiquidity: 50 } });
        const scorer = pick({ symbol: 'SCO', score: 95, categoryScores: { value: 90, growth: 90, profitability: 90, cashFlow: 90, momentum: 10, debtLiquidity: 90 } });
        getLatestFunnelPicks.mockResolvedValue(funnel([momentumKing, scorer]));
        const result = await generateEnhancedProPicksWithRun({ sortBy: 'momentum' }, { includeSignalOverlays: false });
        expect(result.picks[0].symbol).toBe('MOM');
    });

    it('generateEnhancedProPicks devuelve solo la lista', async () => {
        getLatestFunnelPicks.mockResolvedValue(funnel([tech]));
        expect(await generateEnhancedProPicks({ minScore: 70 })).toHaveLength(1);
    });
});

describe('attachSignalOverlays', () => {
    it('lista vacía -> lista vacía sin tocar el módulo de señales', async () => {
        expect(await attachSignalOverlays([])).toEqual([]);
        expect(getSignalOverlays).not.toHaveBeenCalled();
    });

    it('overlay positivo sube confianza +2 y vuelca ov_<metric> en facts', async () => {
        getSignalOverlays.mockResolvedValue([{ metric: 'insider', value: 3, impact: 5 }]);
        const [result] = await attachSignalOverlays([pick({ confidence: 72, confidenceLevel: 'Media' })]);
        expect(result.confidence).toBe(74);
        expect(result.facts['ov_insider']).toBe(3);
        expect(result.overlays).toHaveLength(1);
    });

    it('overlay negativo baja -3; el delta total se acota a ±6 y la confianza a 5-97', async () => {
        getSignalOverlays.mockResolvedValue([
            { metric: 'a', value: 1, impact: -5 },
            { metric: 'b', value: 2, impact: -5 },
            { metric: 'c', value: 3, impact: -5 },
        ]);
        const [down] = await attachSignalOverlays([pick({ confidence: 20, confidenceLevel: 'Baja' })]);
        expect(down.confidence).toBe(14); // 20 - 6 (tope), no 20 - 9
        getSignalOverlays.mockResolvedValue([
            { metric: 'a', value: 1, impact: 5 },
            { metric: 'b', value: 1, impact: 5 },
            { metric: 'c', value: 1, impact: 5 },
            { metric: 'd', value: 1, impact: 5 },
        ]);
        const [up] = await attachSignalOverlays([pick({ confidence: 95, confidenceLevel: 'Alta' })]);
        expect(up.confidence).toBe(97); // techo
    });

    it('la métrica que ya trae prefijo ov_ no se duplica', async () => {
        getSignalOverlays.mockResolvedValue([{ metric: 'ov_revisiones', value: 4, impact: 2 }]);
        const [result] = await attachSignalOverlays([pick()]);
        expect(result.facts['ov_revisiones']).toBe(4);
        expect(result.facts).not.toHaveProperty('ov_ov_revisiones');
    });

    it('overlay sin metric o sin valor no entra en facts; neutro no mueve la confianza', async () => {
        getSignalOverlays.mockResolvedValue([{ value: 1, impact: 0 }, { metric: 'x', impact: 0 }]);
        const original = pick({ confidence: 72 });
        const [result] = await attachSignalOverlays([original]);
        expect(result.confidence).toBe(72);
        expect(result.facts).toEqual(original.facts);
    });

    it('sin impact numérico, la dirección en texto marca el sentimiento', async () => {
        getSignalOverlays.mockResolvedValue([
            { metric: 'a', value: 1, direction: 'bullish' },
            { metric: 'b', value: 1, direction: 'bearish' },
            { metric: 'c', value: 1, direction: 'neutral' },
            { metric: 'd', value: 1 },
        ]);
        const [result] = await attachSignalOverlays([pick({ confidence: 72 })]);
        // +2 (bullish) -3 (bearish) + 0 + 0 = -1
        expect(result.confidence).toBe(71);
    });

    it('un símbolo que falla no tumba al resto: ese pick queda intacto', async () => {
        getSignalOverlays
            .mockRejectedValueOnce(new Error('fuente caída'))
            .mockResolvedValueOnce([{ metric: 'insider', value: 1, impact: 5 }]);
        const [a, b] = await attachSignalOverlays([pick({ symbol: 'BAD' }), pick({ symbol: 'OK', confidence: 72 })]);
        expect(a.symbol).toBe('BAD');
        expect(a.overlays).toBeUndefined();
        expect(b.confidence).toBe(74);
    });

    it('sin overlays para un pick, el pick se devuelve tal cual', async () => {
        getSignalOverlays.mockResolvedValue([]);
        const original = pick();
        const [result] = await attachSignalOverlays([original]);
        expect(result).toBe(original);
    });

    it('cruce de nivel: 79 -> 81 pasa de Media a Alta', async () => {
        getSignalOverlays.mockResolvedValue([{ metric: 'insider', value: 1, impact: 5 }]);
        const [result] = await attachSignalOverlays([pick({ confidence: 79, confidenceLevel: 'Media' })]);
        expect(result.confidence).toBe(81);
        expect(result.confidenceLevel).toBe('Alta');
    });
});
