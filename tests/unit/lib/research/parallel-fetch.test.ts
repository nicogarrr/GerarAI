import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    degradedReasons, launchResearchBatch, pick, researchFailureReason, settleResearchBatch, type ResearchSettled,
} from '@/lib/research/parallel-fetch';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('researchFailureReason', () => {
    it('distingue timeout, abort, mensaje y valores crudos', () => {
        expect(researchFailureReason(new DOMException('t', 'TimeoutError'))).toBe('timeout');
        expect(researchFailureReason(new DOMException('a', 'AbortError'))).toBe('abort');
        expect(researchFailureReason(new Error('boom'))).toBe('boom');
        expect(researchFailureReason({ message: '' })).toBe('[object Object]');
        expect(researchFailureReason('texto')).toBe('texto');
        expect(researchFailureReason(null)).toBe('null');
    });
});

describe('settleResearchBatch', () => {
    it('una tarea que falla no tumba a las demás', async () => {
        const out = await settleResearchBatch([
            { key: 'a', promise: Promise.resolve(1) },
            { key: 'b', promise: Promise.reject(new Error('x')) },
        ]);
        expect(out[0]).toEqual({ key: 'a', ok: true, value: 1 });
        expect(out[1]).toMatchObject({ key: 'b', ok: false, reason: 'x' });
    });
    it('una tarea colgada se corta por presupuesto como timeout', async () => {
        const hang = new Promise<number>(() => {});
        const p = settleResearchBatch([{ key: 'h', promise: hang }, { key: 'ok', promise: Promise.resolve(2) }], 1000);
        await vi.advanceTimersByTimeAsync(1001);
        expect(await p).toEqual([{ key: 'h', ok: false, reason: 'timeout' }, { key: 'ok', ok: true, value: 2 }]);
    });
});

describe('launchResearchBatch', () => {
    it('todas las tareas arrancan a la vez y comparten la señal', async () => {
        const seen: AbortSignal[] = [];
        const batch = launchResearchBatch([
            { key: 'a', run: async (s) => { seen.push(s); return 'A'; } },
            { key: 'b', run: async (s) => { seen.push(s); return 'B'; } },
        ]);
        expect(batch.size).toBe(2);
        expect(seen).toHaveLength(2);
        expect(seen[0]).toBe(batch.signal);
        const res = await batch.settle();
        expect(res.map((r) => r.ok)).toEqual([true, true]);
    });
    it('agotado el presupuesto aborta la señal y las tareas que la respetan fallan con abort', async () => {
        const batch = launchResearchBatch([
            { key: 'slow', run: (signal) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason))) },
        ], 500);
        const settled = batch.settle();
        await vi.advanceTimersByTimeAsync(501);
        expect(batch.signal.aborted).toBe(true);
        expect(await settled).toEqual([expect.objectContaining({ key: 'slow', ok: false, reason: 'abort' })]);
    });
    it('un rechazo no manejado antes de settle no revienta el proceso', async () => {
        const batch = launchResearchBatch([{ key: 'x', run: () => Promise.reject(new Error('tarde')) }]);
        await vi.advanceTimersByTimeAsync(10);
        expect(await batch.settle()).toEqual([expect.objectContaining({ ok: false, reason: 'tarde' })]);
    });
});

describe('pick / degradedReasons', () => {
    const settled: ResearchSettled<number>[] = [
        { key: 'a', ok: true, value: 0 },
        { key: 'b', ok: false, reason: 'timeout' },
    ];
    it('pick devuelve el valor (incluso 0) o el respaldo si falló o no existe', () => {
        expect(pick(settled, 'a', 9)).toBe(0);
        expect(pick(settled, 'b', 9)).toBe(9);
        expect(pick(settled, 'zzz', 9)).toBe(9);
    });
    it('degradedReasons lista solo los fallos', () => {
        expect(degradedReasons(settled)).toEqual([{ key: 'b', reason: 'timeout' }]);
        expect(degradedReasons([])).toEqual([]);
    });
});
