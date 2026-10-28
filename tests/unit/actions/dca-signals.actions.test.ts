import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
    revalidatePath: vi.fn(),
}));
vi.mock('next/cache', () => ({ revalidatePath: m.revalidatePath }));
vi.mock('@/lib/research/client', () => ({ researchRequest: m.researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: m.requireAuthenticatedUser }));

import { AppError } from '@/lib/types/errors';
import {
    evaluateDcaSignalsNow,
    getDcaBacktest,
    getDcaHitRates,
    getDcaHitRatesState,
    getDcaSignals,
} from '@/lib/actions/dca-signals.actions';

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    m.requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-dca' });
});

describe('getDcaSignals', () => {
    it('devuelve las señales cuando el backend manda una lista', async () => {
        const payload = { items: [{ symbol: 'AAPL', level: 2 }] };
        m.researchRequest.mockResolvedValueOnce(payload);
        expect(await getDcaSignals()).toEqual({ data: payload, unavailable: false });
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist/dca-signals');
    });

    it('sin lista de items o con error es «no disponible», nunca una lista vacía inventada', async () => {
        m.researchRequest.mockResolvedValueOnce({ items: null });
        expect(await getDcaSignals()).toEqual({ data: null, unavailable: true });
        m.researchRequest.mockResolvedValueOnce(null);
        expect(await getDcaSignals()).toEqual({ data: null, unavailable: true });
        m.researchRequest.mockRejectedValueOnce(new AppError('down', 'RESEARCH_API_ERROR', 503));
        expect(await getDcaSignals()).toEqual({ data: null, unavailable: true });
    });
});

describe('evaluateDcaSignalsNow', () => {
    it('POST al evaluador, revalida /watchlist y devuelve el resumen', async () => {
        m.researchRequest.mockResolvedValueOnce({ evaluated: 3 });
        expect(await evaluateDcaSignalsNow()).toEqual({ success: true, summary: { evaluated: 3 } });
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist/dca-signals/evaluate', { method: 'POST' });
        expect(m.revalidatePath).toHaveBeenCalledWith('/watchlist');
    });

    it('el límite de una por minuto llega como fallo con mensaje, sin revalidar', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('Rate limit exceeded', 'RESEARCH_API_ERROR', 429));
        const result = await evaluateDcaSignalsNow();
        expect(result.success).toBe(false);
        expect(result.message).toBe('Demasiadas peticiones. Espera un momento y reintenta.');
        expect(m.revalidatePath).not.toHaveBeenCalled();
    });
});

describe('getDcaHitRatesState', () => {
    it('ok con datos; la ruta lleva el símbolo codificado', async () => {
        m.researchRequest.mockResolvedValueOnce({ symbol: 'BRK.B', rates: [] });
        expect(await getDcaHitRatesState('BRK.B')).toEqual({ status: 'ok', data: { symbol: 'BRK.B', rates: [] } });
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist/dca-signals/BRK.B/hit-rates');
    });

    it('solo el 404 específico del backend es «sin señal evaluada»', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('AAPL sin señal DCA evaluada', 'RESEARCH_API_ERROR', 404));
        expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'not_evaluated' });
    });

    it('un 404 genérico (proxy, deploy) o un 500 es «no disponible»', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('Not Found', 'RESEARCH_API_ERROR', 404));
        expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'unavailable' });
        m.researchRequest.mockRejectedValueOnce(new AppError('boom', 'RESEARCH_API_ERROR', 500));
        expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'unavailable' });
        m.researchRequest.mockResolvedValueOnce(null);
        expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'unavailable' });
    });

    it('getDcaHitRates aplana a datos o null', async () => {
        m.researchRequest.mockResolvedValueOnce({ symbol: 'AAPL' });
        expect(await getDcaHitRates('AAPL')).toEqual({ symbol: 'AAPL' });
        m.researchRequest.mockRejectedValueOnce(new AppError('AAPL sin señal DCA evaluada', 'RESEARCH_API_ERROR', 404));
        expect(await getDcaHitRates('AAPL')).toBeNull();
    });
});

describe('getDcaBacktest', () => {
    it('normaliza el ticker y solo manda parámetros válidos', async () => {
        m.researchRequest.mockResolvedValueOnce({ flat: {}, levels: {} });
        const out = await getDcaBacktest({ symbol: ' vod.l ', start: '2020-01-01', end: '2025-12-31', base: 300 });
        expect(out).toEqual({ data: { flat: {}, levels: {} }, error: null });
        expect(m.researchRequest).toHaveBeenCalledWith(
            '/api/watchlist/dca-signals/VOD.L/backtest?start=2020-01-01&end=2025-12-31&base=300',
        );
    });

    it.each([0, -100, Number.NaN, Number.POSITIVE_INFINITY])('una base %s no se envía', async (base) => {
        m.researchRequest.mockResolvedValueOnce({});
        await getDcaBacktest({ symbol: 'AAPL', base });
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist/dca-signals/AAPL/backtest');
    });

    it.each(['', 'AA PL', 'X'.repeat(25), '../etc', 'AAPL;DROP'])('un ticker no válido (%j) no llega al backend', async (symbol) => {
        expect(await getDcaBacktest({ symbol })).toEqual({ data: null, error: 'Ticker no válido' });
        expect(m.researchRequest).not.toHaveBeenCalled();
    });

    it('acepta índices y clases (^GSPC, BRK-B, EURUSD=X)', async () => {
        m.researchRequest.mockResolvedValue({});
        for (const symbol of ['^GSPC', 'BRK-B', 'EURUSD=X']) {
            expect((await getDcaBacktest({ symbol })).error).toBeNull();
        }
        expect(m.researchRequest).toHaveBeenCalledWith('/api/watchlist/dca-signals/%5EGSPC/backtest');
    });

    it('un fallo del backend devuelve un mensaje amable', async () => {
        m.researchRequest.mockRejectedValueOnce(new AppError('down', 'RESEARCH_API_ERROR', 503));
        const out = await getDcaBacktest({ symbol: 'AAPL' });
        expect(out.data).toBeNull();
        expect(out.error).toMatch(/motor|disponible|reintenta/i);
    });
});
