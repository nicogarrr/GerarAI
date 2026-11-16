import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { degradedReasons, launchResearchBatch, pick, researchFailureReason, settleResearchBatch } from '@/lib/research/parallel-fetch';
import { dumpResearchTelemetry, enableResearchTelemetry, recordResearchCall, researchTelemetry, researchTelemetrySummary, resetResearchTelemetry, withResearchTelemetry } from '@/lib/research/fetch-telemetry';

beforeEach(() => { vi.useFakeTimers(); resetResearchTelemetry(); enableResearchTelemetry(false); });
afterEach(() => { vi.useRealTimers(); });
describe('parallel research reads preserve useful results', () => {
    it('launches both reads immediately, shares cancellation and preserves order despite out-of-order completion', async () => {
        const signals: AbortSignal[] = []; let resolveSlow!: (n: number) => void;
        const batch = launchResearchBatch([{ key: 'slow', run: signal => { signals.push(signal); return new Promise<number>(r => { resolveSlow = r; }); } }, { key: 'fast', run: async signal => { signals.push(signal); return 2; } }], 1000);
        expect(batch.size).toBe(2); expect(signals).toHaveLength(2); expect(signals[0]).toBe(signals[1]);
        resolveSlow(1); expect(await batch.settle()).toEqual([{ key: 'slow', ok: true, value: 1 }, { key: 'fast', ok: true, value: 2 }]);
        await vi.advanceTimersByTimeAsync(1000); expect(batch.signal.aborted).toBe(false);
    });
    it('degrades a hung widget on its deadline without discarding the completed widget', async () => {
        const result = settleResearchBatch([{ key: 'hung', promise: new Promise<number>(() => {}) }, { key: 'ready', promise: Promise.resolve(0) }], 100);
        await vi.advanceTimersByTimeAsync(99); let settled = false; void result.then(() => { settled = true; }); await Promise.resolve(); expect(settled).toBe(false);
        await vi.advanceTimersByTimeAsync(1); const rows = await result;
        expect(rows).toEqual([{ key: 'hung', ok: false, reason: 'timeout' }, { key: 'ready', ok: true, value: 0 }]);
        expect(pick(rows, 'ready', 99)).toBe(0); expect(pick(rows, 'hung', 99)).toBe(99); expect(pick(rows, 'missing', 99)).toBe(99); expect(degradedReasons(rows)).toEqual([{ key: 'hung', reason: 'timeout' }]);
    });
    it('aborts the shared network signal when the launch budget, not the later collection time, expires', async () => {
        const batch = launchResearchBatch([{ key: 'network', run: signal => new Promise<number>((_, reject) => signal.addEventListener('abort', () => reject(signal.reason))) }], 50);
        await vi.advanceTimersByTimeAsync(50); expect(batch.signal.aborted).toBe(true); const rows = await batch.settle(); expect(rows[0]).toMatchObject({ key: 'network', ok: false, reason: 'abort' });
    });
    it('preserves the original error without rejecting the whole page and handles an empty batch', async () => {
        const error = new Error('upstream 503'); const rows = await settleResearchBatch([{ key: 'failed', promise: Promise.reject(error) }]); expect(rows).toEqual([{ key: 'failed', ok: false, reason: 'upstream 503', error }]); expect(await launchResearchBatch([]).settle()).toEqual([]);
    });
    it.each([[new DOMException('slow', 'TimeoutError'), 'timeout'], [new DOMException('stop', 'AbortError'), 'abort'], [{ message: 'backend reason' }, 'backend reason'], [{ message: '' }, '[object Object]'], [null, 'null'], ['offline', 'offline']])('keeps an honest degradation reason for %s', (value, expected) => { expect(researchFailureReason(value)).toBe(expected); });
});
describe('research telemetry does not change the request contract', () => {
    it('records elapsed time and returns the original successful value', async () => {
        const value = { price: 0 }; const pending = withResearchTelemetry('/snapshot', async () => { await new Promise(r => setTimeout(r, 37)); return value; }); await vi.advanceTimersByTimeAsync(37); expect(await pending).toBe(value); expect(researchTelemetry()).toEqual([{ endpoint: '/snapshot', ms: 37, ok: true, status: 200 }]);
    });
    it.each([[new DOMException('slow', 'TimeoutError'), 'timeout', undefined], [new DOMException('stop', 'AbortError'), 'abort', undefined], [{ statusCode: 503, message: 'offline' }, 'offline', 503], [{ statusCode: '503', message: '' }, '[object Object]', undefined], [null, 'null', undefined], ['network', 'network', undefined]])('records but rethrows %s unchanged', async (error, reason, status) => {
        await expect(withResearchTelemetry('/market', async () => { throw error; })).rejects.toBe(error); expect(researchTelemetry()[0]).toMatchObject({ endpoint: '/market', ok: false, reason }); expect(researchTelemetry()[0].status).toBe(status);
    });
    it('aggregates endpoints by actual total cost and caps stored samples at the latest 200', () => {
        expect(dumpResearchTelemetry()).toBe('research-telemetry: sin muestras');
        recordResearchCall({ endpoint: '/a', ms: 10, ok: true }); recordResearchCall({ endpoint: '/b', ms: 50, ok: false, reason: 'timeout' }); recordResearchCall({ endpoint: '/a', ms: 20, ok: false });
        expect(researchTelemetrySummary()).toEqual([{ endpoint: '/b', calls: 1, failures: 1, totalMs: 50, maxMs: 50 }, { endpoint: '/a', calls: 2, failures: 1, totalMs: 30, maxMs: 20 }]); expect(dumpResearchTelemetry()).toContain('/a calls=2 failures=1 total=30ms max=20ms');
        for (let i = 0; i < 201; i++) recordResearchCall({ endpoint: `/${i}`, ms: i, ok: true }); expect(researchTelemetry()).toHaveLength(200); expect(researchTelemetry()[0].endpoint).toBe('/1'); resetResearchTelemetry(); expect(researchTelemetry()).toEqual([]);
    });
    it('logs only when enabled and distinguishes successful status, missing status and failures', () => {
        const log = vi.spyOn(console, 'log').mockImplementation(() => {}); enableResearchTelemetry(); recordResearchCall({ endpoint: '/ok', ms: 1, ok: true, status: 201 }); recordResearchCall({ endpoint: '/empty', ms: 0, ok: true }); recordResearchCall({ endpoint: '/fail', ms: 2, ok: false }); const text = dumpResearchTelemetry(); expect(log).toHaveBeenCalledWith('[research-telemetry] /ok 1ms ok 201'); expect(log).toHaveBeenCalledWith('[research-telemetry] /empty 0ms ok'); expect(log).toHaveBeenCalledWith('[research-telemetry] /fail 2ms FAIL '); expect(log).toHaveBeenCalledWith(text);
    });
});
