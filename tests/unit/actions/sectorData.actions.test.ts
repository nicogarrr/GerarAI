import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchJSON, requireAuthenticatedUser } = vi.hoisted(() => ({
    fetchJSON: vi.fn(),
    requireAuthenticatedUser: vi.fn(async () => ({ id: 'user-1' })),
}));
vi.mock('@/lib/upstream/finnhub', () => ({ fetchJSON }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import { getSectorAverages } from '@/lib/actions/sectorData.actions';

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    // Delay anti-rate-limit instantáneo en tests
    vi.spyOn(global, 'setTimeout').mockImplementation(((fn: () => void) => { fn(); return 0; }) as never);
    process.env.FINNHUB_API_KEY = 'key';
});

describe('honestidad: sin datos reales, null (nunca inventados)', () => {
    it('sin API key -> null', async () => {
        delete process.env.FINNHUB_API_KEY;
        expect(await getSectorAverages('Technology')).toBeNull();
        expect(fetchJSON).not.toHaveBeenCalled();
    });

    it('sector sin acciones representativas -> null', async () => {
        expect(await getSectorAverages('Sector Inexistente')).toBeNull();
        expect(fetchJSON).not.toHaveBeenCalled();
    });

    it('API caída para todas -> null', async () => {
        fetchJSON.mockRejectedValue(new Error('429'));
        expect(await getSectorAverages('Technology')).toBeNull();
    });
});

describe('promedios del sector', () => {
    it('media de las métricas disponibles; porcentajes como FRACCIÓN (15% = 0.15)', async () => {
        fetchJSON.mockImplementation(async (url: string) => {
            if (String(url).includes('AAPL')) return { metric: { peTTM: 20, pbTTM: 5, psTTM: 4, roeTTM: 30, roaTTM: 15, netProfitMarginTTM: 25, revenueGrowthTTM: 12, debtToEquityTTM: 50, currentRatioTTM: 2 } };
            throw new Error('sin datos');
        });
        const result = await getSectorAverages('Technology');
        expect(result).not.toBeNull();
        expect(result!.sampleSize).toBe(1);
        expect(result!.metrics.avgPE).toBe(20);
        expect(result!.metrics.avgROE).toBeCloseTo(0.3, 10); // fracción, no 30
        expect(result!.metrics.avgNetMargin).toBeCloseTo(0.25, 10);
        expect(result!.averages.cashFlow).toBeNull(); // sin datos sectoriales de FCF
        expect(result!.averages.momentum).toBeNull(); // sin histórico sectorial
        expect(result!.unitTrace).toEqual({
            inputPercentageUnit: 'assumed_percent_not_provider_verified',
            outputPercentageUnit: 'fraction',
            missing: 'null',
        });
    });

    it('métrica sin ningún dato -> score null (un promedio vacío no es un 0)', async () => {
        fetchJSON.mockResolvedValue({ metric: { peTTM: 20 } });
        const result = await getSectorAverages('Technology');
        expect(result!.metrics.avgPE).toBe(20);
        expect(result!.averages.value).toBeNull(); // faltan PB y PS
        expect(result!.averages.growth).toBeNull();
        expect(result!.metrics.avgDebtToEquity).toBeNull();
    });

    it('un fallo puntual de un símbolo no tira el sector', async () => {
        let calls = 0;
        fetchJSON.mockImplementation(async () => {
            calls += 1;
            if (calls === 1) throw new Error('timeout');
            return { metric: { peTTM: 10, pbTTM: 2, psTTM: 1, roeTTM: 10, roaTTM: 5, netProfitMarginTTM: 10, revenueGrowthTTM: 6, debtToEquityTTM: 30, currentRatioTTM: 1.5 } };
        });
        const result = await getSectorAverages('Technology');
        expect(result!.sampleSize).toBe(9); // 10 intentos - 1 fallido
        expect(result!.averages.value).not.toBeNull();
    });
});
