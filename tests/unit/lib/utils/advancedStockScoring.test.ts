// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ sector: vi.fn() }));
vi.mock('@/lib/actions/sectorData.actions', () => ({ getSectorAverages: mocks.sector }));

import { calculateAdvancedStockScore, SCORING_WEIGHTS } from '@/lib/utils/advancedStockScoring';

const METRICS = {
    peTTM: 10, pbTTM: 1, psTTM: 2, evEbitdaTTM: 10,
    revenueGrowthTTMYoy: 20, epsGrowthTTMYoy: 25, ebitdaCagr5Y: 20,
    netProfitMarginTTM: 25, roeTTM: 30, roaTTM: 12,
    pfcfShareTTM: 10, cashFlowPerShareTTM: 5,
    'totalDebt/totalEquityQuarterly': 0.3, currentRatioQuarterly: 2.5,
    quickRatioQuarterly: 2, netInterestCoverageTTM: 6,
};
const PROFILE = { finnhubIndustry: 'Technology' };

function candles(n: number) {
    const base = Date.UTC(2025, 0, 1) / 1000;
    return {
        prices: Array.from({ length: n }, (_, i) => i + 1),
        dates: Array.from({ length: n }, (_, i) => base + i * 86_400),
        base,
    };
}

beforeEach(() => {
    mocks.sector.mockReset();
});

describe('calculateAdvancedStockScore - sin datos de sector', () => {
    it('puntúa con benchmarks genéricos y deja sectorComparison en null (no inventa comparación)', async () => {
        mocks.sector.mockResolvedValue(null);
        const r = await calculateAdvancedStockScore({ metrics: { metric: METRICS }, profile: PROFILE, quote: {} });
        expect(r.sectorComparison).toBeNull();
        expect(r.categoryScores).toEqual({ value: 100, growth: 85, profitability: 90, cashFlow: 70, momentum: 0, debtLiquidity: 100 });
        expect(r.overallScore).toBe(80);
        expect(r.grade).toBe('B+');
        expect(r.facts).toMatchObject({ sector: 'Technology', pe: 10, roe: 30 });
        // Sin medias reales del sector los textos no dicen «vs sector».
        expect(r.reasons.strengths).toContain('PER bajo (10,0)');
        expect(r.reasons.strengths).toContain('Baja deuda (D/E: 0,30)');
        expect(r.reasons.strengths.join(' ')).not.toContain('vs sector');
    });

    it('sin ninguna métrica: todo a 0, nota F, sin razones inventadas', async () => {
        mocks.sector.mockResolvedValue(null);
        const r = await calculateAdvancedStockScore({ metrics: {}, profile: {}, quote: {} });
        expect(r.overallScore).toBe(0);
        expect(r.grade).toBe('F');
        expect(r.reasons.strengths).toEqual([]);
        expect(r.facts.sector).toBe('Desconocido');
    });

    it('acepta métricas como strings numéricos', async () => {
        mocks.sector.mockResolvedValue(null);
        const r = await calculateAdvancedStockScore({ metrics: { metric: { peTTM: '10' } }, profile: PROFILE, quote: {} });
        expect(r.categoryScores.value).toBe(30);
        expect(r.facts.pe).toBe(10);
    });

    it('un P/FCF negativo es FCF negativo, no una ganga (V5)', async () => {
        mocks.sector.mockResolvedValue(null);
        const r = await calculateAdvancedStockScore({ metrics: { metric: { pfcfShareTTM: -5 } }, profile: PROFILE, quote: {} });
        expect(r.categoryScores.cashFlow).toBe(0);
        expect(r.reasons.weaknesses).toContain('FCF por acción negativo (P/FCF sin lectura de valor)');
    });
});

describe('calculateAdvancedStockScore - con datos reales del sector', () => {
    const SECTOR = {
        averages: { value: 40, growth: 30, profitability: 50, cashFlow: null, momentum: null, debtLiquidity: 60 },
        metrics: { avgPE: 20, avgPB: 3, avgRevenueGrowth: 0.1, avgNetMargin: 0.1, avgDebtToEquity: 1 },
    };
    it('compara contra el sector con la MISMA fórmula en ambos lados (V7)', async () => {
        mocks.sector.mockResolvedValue(SECTOR);
        const r = await calculateAdvancedStockScore({ metrics: { metric: METRICS }, profile: PROFILE, quote: {} });
        expect(r.overallScore).toBe(86);
        expect(r.grade).toBe('A-');
        expect(r.sectorComparison?.sector).toBe('Technology');
        expect(r.sectorComparison?.vsSector).toEqual({
            value: 60, growth: 50, profitability: 50, cashFlow: null, momentum: null, debtLiquidity: 10,
        });
        expect(r.reasons.strengths).toContain('PER bajo vs sector (10,0 vs 20,0)');
        expect(r.reasons.strengths.join(' ')).toContain('Crecimiento superior al sector');
        expect(r.reasons.strengths.join(' ')).toContain('Margen neto superior al sector');
        expect(r.reasons.strengths.join(' ')).toContain('Baja deuda vs sector');
    });

    it('los pesos del score final son los de SCORING_WEIGHTS (suma 1)', () => {
        const suma = Object.values(SCORING_WEIGHTS).reduce((a, b) => a + b, 0);
        expect(suma).toBeCloseTo(1);
    });
});

describe('calculateAdvancedStockScore - corte temporal point-in-time', () => {
    it('con asOf explícito filtra las velas posteriores: el precio en facts es el del corte', async () => {
        mocks.sector.mockResolvedValue(null);
        const { base, ...series } = candles(300);
        const asOf = new Date((base + 100 * 86_400) * 1000).toISOString();
        const r = await calculateAdvancedStockScore({ metrics: {}, profile: PROFILE, quote: {} }, series, asOf);
        expect(r.asOf).toBe(asOf);
        expect(r.facts.price).toBe(101); // vela 100, no la 300 (futuro)
        expect(r.facts.return3M).toBeCloseTo(158.97, 2);
        expect(r.facts.return6M).toBeUndefined(); // 101 velas no dan para 6 meses
        expect(r.facts.return12M).toBeUndefined();
    });

    it('con asOf explícito NO usa quote.dp ni la comparación con el S&P 500 (no demostrables PIT)', async () => {
        mocks.sector.mockResolvedValue(null);
        const { base, ...series } = candles(300);
        const asOf = new Date((base + 100 * 86_400) * 1000).toISOString();
        const quote = { dp: 5, t: base + 200 * 86_400 }; // timestamp posterior al corte
        const r = await calculateAdvancedStockScore(
            { metrics: {}, profile: PROFILE, quote, indexComparison: { vsSP500: { change: 10 } } },
            series, asOf,
        );
        // Momentum = solo el tramo 3M de las velas filtradas (20 puntos).
        expect(r.categoryScores.momentum).toBe(20);
        expect(r.reasons.strengths.join(' ')).not.toContain('S&P 500');
    });

    it('sin asOf explícito el corte es la última vela y sí entran quote.dp y S&P 500', async () => {
        mocks.sector.mockResolvedValue(null);
        const { base, ...series } = candles(300);
        const quote = { dp: 5, t: base + 299 * 86_400, c: 300 };
        const r = await calculateAdvancedStockScore(
            { metrics: {}, profile: PROFILE, quote, indexComparison: { vsSP500: { change: 10 } } },
            series,
        );
        expect(r.asOf).toBe(new Date((base + 299 * 86_400) * 1000).toISOString());
        expect(r.categoryScores.momentum).toBe(100); // 20+20+20+20+15+20, cap 100
        expect(r.facts.price).toBe(300);
        expect(r.reasons.strengths.join(' ')).toContain('Supera al S&P 500');
        expect(r.reasons.opportunities).toContain('Cerca del máximo de 52 semanas');
    });
});

describe('claves reales de Finnhub (/stock/metric?metric=all, verificado en vivo 2026-10-31)', () => {
    it('lee P/B desde pbQuarterly/pbAnnual cuando no hay pbTTM ni pb', async () => {
        mocks.sector.mockResolvedValue(null);
        const r = await calculateAdvancedStockScore({
            metrics: { metric: { pbQuarterly: 1.5 } }, profile: PROFILE, quote: {},
        });
        // pb 1.5 < 2 -> 25 puntos de valor; sin la clave real el P/B no puntuaba.
        expect(r.categoryScores.value).toBe(25);
        expect(r.facts.pb).toBe(1.5);
    });

    it('lee D/E y liquidez desde las claves reales del payload', async () => {
        mocks.sector.mockResolvedValue(null);
        const r = await calculateAdvancedStockScore({
            metrics: { metric: { 'totalDebt/totalEquityQuarterly': 0.3, currentRatioQuarterly: 2.5 } },
            profile: PROFILE, quote: {},
        });
        expect(r.categoryScores.debtLiquidity).toBe(60); // 35 (D/E bajo) + 25 (current > 2)
        expect(r.facts.debtToEquity).toBe(0.3);
        expect(r.facts.currentRatio).toBe(2.5);
    });
});
