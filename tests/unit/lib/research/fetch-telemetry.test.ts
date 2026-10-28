import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    dumpResearchTelemetry, enableResearchTelemetry, recordResearchCall, researchTelemetry, researchTelemetrySummary,
    resetResearchTelemetry, withResearchTelemetry,
} from '@/lib/research/fetch-telemetry';

beforeEach(() => { resetResearchTelemetry(); enableResearchTelemetry(false); });
afterEach(() => { enableResearchTelemetry(false); });

describe('telemetría de research', () => {
    it('sin muestras', () => {
        expect(dumpResearchTelemetry()).toBe('research-telemetry: sin muestras');
        expect(researchTelemetrySummary()).toEqual([]);
    });
    it('resume por endpoint, cuenta fallos y ordena por tiempo total', () => {
        recordResearchCall({ endpoint: '/a', ms: 10, ok: true });
        recordResearchCall({ endpoint: '/b', ms: 500, ok: false, reason: 'timeout' });
        recordResearchCall({ endpoint: '/a', ms: 30, ok: true });
        expect(researchTelemetrySummary()).toEqual([
            { endpoint: '/b', calls: 1, failures: 1, totalMs: 500, maxMs: 500 },
            { endpoint: '/a', calls: 2, failures: 0, totalMs: 40, maxMs: 30 },
        ]);
        expect(dumpResearchTelemetry()).toContain('/b calls=1 failures=1 total=500ms max=500ms');
    });
    it('guarda como mucho las últimas 200 muestras', () => {
        for (let i = 0; i < 250; i++) recordResearchCall({ endpoint: `/e${i}`, ms: 1, ok: true });
        const all = researchTelemetry();
        expect(all).toHaveLength(200);
        expect(all[0].endpoint).toBe('/e50');
        expect(all[199].endpoint).toBe('/e249');
    });
    it('withResearchTelemetry registra éxito y devuelve el valor', async () => {
        await expect(withResearchTelemetry('/ok', async () => 42)).resolves.toBe(42);
        expect(researchTelemetry()[0]).toMatchObject({ endpoint: '/ok', ok: true, status: 200 });
    });
    it('registra el fallo con estado y motivo y relanza el MISMO error', async () => {
        const err = Object.assign(new Error('caído'), { statusCode: 503 });
        await expect(withResearchTelemetry('/bad', async () => { throw err; })).rejects.toBe(err);
        expect(researchTelemetry()[0]).toMatchObject({ endpoint: '/bad', ok: false, status: 503, reason: 'caído' });
    });
    it('motivo timeout/abort/valor crudo y sin estado numérico', async () => {
        await withResearchTelemetry('/t', async () => { throw new DOMException('x', 'TimeoutError'); }).catch(() => null);
        await withResearchTelemetry('/a', async () => { throw new DOMException('x', 'AbortError'); }).catch(() => null);
        await withResearchTelemetry('/s', async () => { throw 'texto'; }).catch(() => null);
        await withResearchTelemetry('/c', async () => { throw Object.assign(new Error('e'), { statusCode: '500' }); }).catch(() => null);
        const [t, a, s, c] = researchTelemetry();
        expect([t.reason, a.reason, s.reason]).toEqual(['timeout', 'abort', 'texto']);
        expect(s.status).toBeUndefined();
        expect(c.status).toBeUndefined();
    });
    it('modo verbose escribe en consola; sin él, silencio', () => {
        const log = vi.spyOn(console, 'log').mockImplementation(() => {});
        recordResearchCall({ endpoint: '/q', ms: 1, ok: true });
        expect(log).not.toHaveBeenCalled();
        enableResearchTelemetry();
        recordResearchCall({ endpoint: '/q', ms: 2, ok: true, status: 200 });
        recordResearchCall({ endpoint: '/q', ms: 3, ok: false, reason: 'x' });
        expect(log).toHaveBeenCalledWith('[research-telemetry] /q 2ms ok 200');
        expect(log).toHaveBeenCalledWith('[research-telemetry] /q 3ms FAIL x');
        dumpResearchTelemetry();
        expect(log).toHaveBeenCalledTimes(3);
    });
});
