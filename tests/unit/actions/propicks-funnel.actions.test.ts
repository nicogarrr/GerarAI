import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));

import { getLatestFunnelPicks, generateFunnelRunNow } from '@/lib/actions/propicks-funnel.actions';
import { PROPICKS_SCORING_WEIGHTS } from '@/lib/utils/propicksValidation';

const candidate = (over: object = {}) => ({
    company_id: 1,
    ticker: 'AAPL',
    name: 'Apple',
    sector: 'Technology',
    currency: 'USD',
    passed: true,
    rank: 1,
    score: 80,
    failed_gates: [],
    metrics: {},
    coverage: {},
    current_price: 150,
    price_as_of: '2026-10-27',
    ...over,
});

const detail = (candidates: object[], over: object = {}) => ({
    id: 9, as_of: '2026-10-27', status: 'completed', universe_size: 500, passed_count: 1, top_n: 5,
    candidates, ...over,
});

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('getLatestFunnelPicks: selección del run', () => {
    it('sin runs o sin runs completados -> null', async () => {
        researchRequest.mockResolvedValue([]);
        expect(await getLatestFunnelPicks()).toBeNull();
        researchRequest.mockResolvedValue([{ id: 3, status: 'running' }]);
        expect(await getLatestFunnelPicks()).toBeNull();
    });

    it('elige el run completado más reciente por id y pide solo passed', async () => {
        researchRequest
            .mockResolvedValueOnce([
                { id: 7, status: 'completed' },
                { id: 9, status: 'completed' },
                { id: 10, status: 'failed' },
            ])
            .mockResolvedValueOnce(detail([candidate()]));
        const result = await getLatestFunnelPicks();
        expect(researchRequest).toHaveBeenNthCalledWith(2, '/api/propicks/runs/9?only_passed=true', { fast: true });
        expect(result).toMatchObject({ runId: 9, runAsOf: '2026-10-27', universeSize: 500, passedCount: 1 });
    });

    it('descarta no-passed y sin rank, ordena por rank', async () => {
        researchRequest
            .mockResolvedValueOnce([{ id: 9, status: 'completed' }])
            .mockResolvedValueOnce(detail([
                candidate({ ticker: 'SEGUNDO', rank: 2 }),
                candidate({ ticker: 'NO_PASS', passed: false, rank: 0 }),
                candidate({ ticker: 'SIN_RANK', rank: null }),
                candidate({ ticker: 'PRIMERO', rank: 1 }),
            ]));
        const result = await getLatestFunnelPicks();
        expect(result?.picks.map((p) => p.symbol)).toEqual(['PRIMERO', 'SEGUNDO']);
    });
});

describe('funnelCandidateToProPick: escalas deterministas documentadas', () => {
    const fullMetrics = {
        quality_moat_score_v2: 6,          // 6/8 -> 75
        cfroi_approx: 0.15, wacc: 0.09,    // spread +6pp -> 50+30 = 80
        revenue_cagr: 0.12,                // -> 50+30 = 80
        fcf_margin_5y: 0.125,              // -> 50
        momentum_12m: 0.2,                 // -> 50+20 = 70
        net_debt_to_ebitda: 2,             // -> 100-50 = 50
        roic: 0.18, roe_5y: 0.22,
    };

    const getPick = async (metrics: object, over: object = {}) => {
        researchRequest
            .mockResolvedValueOnce([{ id: 9, status: 'completed' }])
            .mockResolvedValueOnce(detail([candidate({ metrics, ...over })]));
        const result = await getLatestFunnelPicks();
        return result!.picks[0];
    };

    it('mapea métricas reales a categorías con las fórmulas documentadas y score con pesos canónicos', async () => {
        const p = await getPick(fullMetrics);
        expect(p.categoryScores).toEqual({
            value: 80, growth: 80, profitability: 75, cashFlow: 50, momentum: 70, debtLiquidity: 50,
        });
        const w = PROPICKS_SCORING_WEIGHTS;
        const expected = Math.round(
            80 * w.value + 80 * w.growth + 75 * w.profitability + 50 * w.cashFlow + 70 * w.momentum + 50 * w.debtLiquidity,
        );
        expect(p.score).toBe(expected);
        expect(p.facts['cfroi_approx']).toBe(15);
        expect(p.facts['wacc']).toBe(9);
        expect(p.facts['revenue_cagr']).toBe(12);
        expect(p.facts['net_debt_to_ebitda']).toBe(2);
        expect(p.facts['spread_cfroi_wacc']).toBe(6);
    });

    it('métrica ausente -> categoría 50 neutral marcada en facts, nunca inventada', async () => {
        const p = await getPick({});
        expect(p.categoryScores).toEqual({
            value: 50, growth: 50, profitability: 50, cashFlow: 50, momentum: 50, debtLiquidity: 50,
        });
        for (const flag of ['moat_neutral_sin_datos', 'valoracion_neutral_sin_datos', 'crecimiento_neutral_sin_datos',
            'fcf_neutral_sin_datos', 'momentum_neutral_sin_datos', 'deuda_neutral_sin_datos']) {
            expect(p.facts[flag]).toBe('si');
        }
        expect(p.confidenceReasons).toEqual([]);
        expect(p.reasons).toEqual([]);
    });

    it('los motivos llevan el número en formato es-ES (coma decimal)', async () => {
        const p = await getPick({ cfroi_approx: 0.125, wacc: 0.085, revenue_cagr: 0.1 });
        const spread = p.confidenceReasons.find((r) => r.metric === 'spread_cfroi_wacc');
        expect(spread?.text).toContain('12,5 % vs WACC 8,5 %');
        expect(spread?.text).toContain('spread de 4 puntos');
        const cagr = p.confidenceReasons.find((r) => r.metric === 'revenue_cagr');
        expect(cagr?.text).toBe('Ingresos creciendo al 10 % anual (5 años)');
    });

    it('extremos se acotan a 0-100 (spread +20pp no da 150)', async () => {
        const p = await getPick({ cfroi_approx: 0.3, wacc: 0.05, net_debt_to_ebitda: 9 });
        expect(p.categoryScores.value).toBe(100);
        expect(p.categoryScores.debtLiquidity).toBe(0);
    });

    it('precio ausente -> precio_pendiente declarado, sin currentPrice en facts', async () => {
        const p = await getPick({}, { current_price: null, price_as_of: null });
        expect(p.currentPrice).toBe(0);
        expect(p.facts['precio_pendiente']).toBe('si');
        expect(p.facts).not.toHaveProperty('currentPrice');
        expect(p.priceAsOf).toBeUndefined();
    });

    it('grade y confianza por bandas; motivos limitados a 3', async () => {
        const all = await getPick({ ...fullMetrics, fcf_margin_5y: 0.3 });
        expect(all.confidenceReasons.length).toBeLessThanOrEqual(3);
        const low = await getPick({ quality_moat_score_v2: 1 });
        expect(low.grade).toBeDefined();
        expect(['Alta', 'Media', 'Baja']).toContain(low.confidenceLevel);
        // score bajo -> banda 45 -> Baja
        const p50 = await getPick({});
        expect(p50.score).toBe(50);
        expect(p50.grade).toBe('D');
        expect(p50.confidence).toBe(45);
        expect(p50.confidenceLevel).toBe('Baja');
    });
});

describe('generateFunnelRunNow', () => {
    it('OK -> run creado', async () => {
        researchRequest.mockResolvedValue({ id: 11, status: 'running' });
        expect(await generateFunnelRunNow()).toEqual({ id: 11, status: 'running' });
        expect(researchRequest).toHaveBeenCalledWith('/api/propicks/runs', { method: 'POST' });
    });

    it('error -> { error } con el mensaje, nunca lanza', async () => {
        researchRequest.mockRejectedValue(new Error('rate limit'));
        expect(await generateFunnelRunNow()).toEqual({ error: 'rate limit' });
        researchRequest.mockRejectedValue('cosa rara');
        expect(await generateFunnelRunNow()).toEqual({ error: 'No se pudo generar la selección.' });
    });
});
