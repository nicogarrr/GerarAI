import { afterEach, describe, expect, it, vi } from 'vitest';

import { batchedSymbol, resetBatchedSymbolsForTests } from '@/lib/cache/batch-symbols';

afterEach(() => {
    resetBatchedSymbolsForTests();
    vi.useRealTimers();
});

describe('batchedSymbol', () => {
    it('agrupa N claves de la misma ventana en UNA llamada batch', async () => {
        vi.useFakeTimers();
        const fetchBatch = vi.fn(async (keys: string[]) =>
            Object.fromEntries(keys.map((k) => [k, `v-${k}`])),
        );
        const promises = ['AMZN', 'SPCX', 'GOOGL', 'AMZN'].map((s) => batchedSymbol('t', s, fetchBatch));
        await vi.advanceTimersByTimeAsync(100);
        const values = await Promise.all(promises);
        expect(fetchBatch).toHaveBeenCalledTimes(1);
        expect(fetchBatch).toHaveBeenCalledWith(['AMZN', 'SPCX', 'GOOGL']);
        expect(values).toEqual(['v-AMZN', 'v-SPCX', 'v-GOOGL', 'v-AMZN']);
    });

    it('devuelve null para claves ausentes del mapa', async () => {
        vi.useFakeTimers();
        const fetchBatch = vi.fn(async () => ({ AMZN: 'v' }));
        const p = batchedSymbol<string, string>('t2', 'SPCX', fetchBatch);
        await vi.advanceTimersByTimeAsync(100);
        await expect(p).resolves.toBeNull();
    });

    it('propaga el error del batch a todas las filas en espera', async () => {
        vi.useFakeTimers();
        const fetchBatch = vi.fn(async () => {
            throw new Error('backend caído');
        });
        const p1 = batchedSymbol('t3', 'AMZN', fetchBatch);
        const p2 = batchedSymbol('t3', 'SPCX', fetchBatch);
        const guard1 = expect(p1).rejects.toThrow('backend caído');
        const guard2 = expect(p2).rejects.toThrow('backend caído');
        await vi.advanceTimersByTimeAsync(100);
        await guard1;
        await guard2;
    });

    it('dos ventanas separadas producen dos llamadas batch', async () => {
        vi.useFakeTimers();
        const fetchBatch = vi.fn(async (keys: string[]) =>
            Object.fromEntries(keys.map((k) => [k, k])),
        );
        const p1 = batchedSymbol('t4', 'AMZN', fetchBatch);
        await vi.advanceTimersByTimeAsync(100);
        await p1;
        const p2 = batchedSymbol('t4', 'SPCX', fetchBatch);
        await vi.advanceTimersByTimeAsync(100);
        await p2;
        expect(fetchBatch).toHaveBeenCalledTimes(2);
    });
});
