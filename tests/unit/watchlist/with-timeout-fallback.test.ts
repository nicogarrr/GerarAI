import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { withTimeoutFallback } from '@/lib/watchlist/with-timeout-fallback';

// Prod 2026-11-09: /api/market/changes tardó 8-9 s por HTTP y la watchlist
// esperaba la promesa del cierre datado en el Promise.all de entrada, así que
// el respaldo llegaba después de que las filas ya hubieran quedado N/D. El
// respaldo necesita su propio presupuesto, y su temporizador no puede quedar
// colgado (serverless).
describe('withTimeoutFallback', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('devuelve el valor si la promesa resuelve dentro del presupuesto', async () => {
        const result = withTimeoutFallback(Promise.resolve('valor'), 3000, 'respaldo');
        await vi.runAllTimersAsync();
        await expect(result).resolves.toBe('valor');
    });

    it('devuelve el respaldo cuando la promesa supera el presupuesto', async () => {
        const slow = new Promise<string>((resolve) => setTimeout(() => resolve('tarde'), 10_000));
        const result = withTimeoutFallback(slow, 3000, 'respaldo');
        await vi.advanceTimersByTimeAsync(3001);
        await expect(result).resolves.toBe('respaldo');
    });

    it('una resolución tardía no sustituye al respaldo ya entregado', async () => {
        const slow = new Promise<string>((resolve) => setTimeout(() => resolve('tarde'), 10_000));
        const result = withTimeoutFallback(slow, 3000, 'respaldo');
        await vi.advanceTimersByTimeAsync(10_001);
        await expect(result).resolves.toBe('respaldo');
    });

    it('no deja temporizadores pendientes al asentarse', async () => {
        const result = withTimeoutFallback(Promise.resolve(1), 3000, 0);
        await expect(result).resolves.toBe(1);
        expect(vi.getTimerCount()).toBe(0);
    });

    it('rechaza si la promesa rechaza dentro del presupuesto', async () => {
        const result = withTimeoutFallback(Promise.reject(new Error('fallo')), 3000, 'respaldo');
        await expect(result).rejects.toThrow('fallo');
        expect(vi.getTimerCount()).toBe(0);
    });
});
