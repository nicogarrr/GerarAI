import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/research-identity', () => ({
    normalizeResearchBody: vi.fn(async (body: unknown) => ({ body, contentType: typeof body === 'string' ? 'application/json' : null })),
    researchIdentityHeaders: vi.fn(async () => ({ 'x-research-user': 'u1' })),
}));

import { jsonBody, requestSignal, researchRequest, researchTimeoutFor, RESEARCH_TIMEOUTS } from '@/lib/research/client';

const res = (status: number, body?: unknown, headers: Record<string, string> = {}) =>
    new Response(body === undefined ? null : JSON.stringify(body), { status, statusText: status === 500 ? 'Server Error' : '', headers });

describe('researchTimeoutFor', () => {
    it('timeoutMs explícito válido manda (truncado); inválido se ignora', () => {
        expect(researchTimeoutFor('/x', 'GET', { timeoutMs: 1234.9 })).toBe(1234);
        expect(researchTimeoutFor('/x', 'GET', { timeoutMs: -5 })).toBe(RESEARCH_TIMEOUTS.GLOBAL_MS);
        expect(researchTimeoutFor('/x', 'GET', { timeoutMs: NaN })).toBe(RESEARCH_TIMEOUTS.GLOBAL_MS);
    });
    it('chat POST largo; chat GET normal', () => {
        expect(researchTimeoutFor('/api/chat', 'post')).toBe(RESEARCH_TIMEOUTS.CHAT_MS);
        expect(researchTimeoutFor('/api/chat', 'GET')).toBe(RESEARCH_TIMEOUTS.GLOBAL_MS);
    });
    it('escaneo de insiders solo en GET', () => {
        expect(researchTimeoutFor('/api/insider/signals?x=1', 'GET')).toBe(RESEARCH_TIMEOUTS.INSIDER_SCAN_MS);
        expect(researchTimeoutFor('/api/insider/signals', 'POST')).toBe(RESEARCH_TIMEOUTS.GLOBAL_MS);
    });
    it('rutas rápidas de portada/cartera solo en GET; fast=true también', () => {
        expect(researchTimeoutFor('/api/portfolio/summary', 'GET')).toBe(RESEARCH_TIMEOUTS.GET_FAST_MS);
        expect(researchTimeoutFor('/api/watchlist', 'GET')).toBe(RESEARCH_TIMEOUTS.GET_FAST_MS);
        expect(researchTimeoutFor('/api/portfolio/transactions', 'POST')).toBe(RESEARCH_TIMEOUTS.GLOBAL_MS);
        expect(researchTimeoutFor('/api/otra', 'GET', { fast: true })).toBe(RESEARCH_TIMEOUTS.GET_FAST_MS);
        expect(researchTimeoutFor('/api/otra', 'POST', { fast: true })).toBe(RESEARCH_TIMEOUTS.GLOBAL_MS);
    });
});

describe('requestSignal', () => {
    it('sin señal externa: solo el timeout', () => {
        expect(requestSignal(null, 10_000).aborted).toBe(false);
    });
    it('la señal externa ya abortada aborta la combinada', () => {
        const c = new AbortController();
        c.abort(new Error('adios'));
        expect(requestSignal(c.signal, 10_000).aborted).toBe(true);
    });
    it('abortar después propaga', () => {
        const c = new AbortController();
        const s = requestSignal(c.signal, 10_000);
        expect(s.aborted).toBe(false);
        c.abort();
        expect(s.aborted).toBe(true);
    });
});

describe('researchRequest', () => {
    let fetchMock: ReturnType<typeof vi.fn>;
    beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock); });
    afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

    it('GET ok devuelve el JSON, añade identidad y no usa caché', async () => {
        fetchMock.mockResolvedValueOnce(res(200, { a: 1 }));
        await expect(researchRequest('/api/x')).resolves.toEqual({ a: 1 });
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toMatch(/\/api\/x$/);
        expect(init.cache).toBe('no-store');
        expect((init.headers as Headers).get('x-research-user')).toBe('u1');
    });
    it('POST con cuerpo JSON fija Content-Type; uno propio se respeta', async () => {
        fetchMock.mockImplementation(async () => res(200, {}));
        await researchRequest('/api/x', { method: 'POST', body: jsonBody({ q: 1 }) });
        expect((fetchMock.mock.calls[0][1].headers as Headers).get('Content-Type')).toBe('application/json');
        await researchRequest('/api/x', { method: 'POST', body: '{}', headers: { 'Content-Type': 'text/custom' } });
        expect((fetchMock.mock.calls[1][1].headers as Headers).get('Content-Type')).toBe('text/custom');
    });
    it('204 devuelve undefined sin parsear', async () => {
        fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
        await expect(researchRequest('/api/x', { method: 'DELETE' })).resolves.toBeUndefined();
    });
    it('error HTTP: AppError con el detalle del backend y el código de estado', async () => {
        fetchMock.mockResolvedValueOnce(res(422, { detail: [{ loc: ['body', 'quantity'] }] }));
        await expect(researchRequest('/api/x', { method: 'POST', body: '{}' })).rejects.toMatchObject({
            name: 'AppError', code: 'RESEARCH_API_ERROR', statusCode: 422, message: expect.stringContaining('quantity'),
        });
    });
    it('error HTTP con cuerpo no JSON: cae a "estado texto"', async () => {
        fetchMock.mockResolvedValueOnce(new Response('<html>', { status: 500, statusText: 'Server Error' }));
        await expect(researchRequest('/api/x')).rejects.toMatchObject({ message: '500 Server Error', statusCode: 500 });
    });
    it('fallo de red: ExternalAPIError que no filtra el error interno en el mensaje', async () => {
        fetchMock.mockRejectedValueOnce(new TypeError('ECONNREFUSED 10.0.0.5'));
        const err: any = await researchRequest('/api/x').catch((e: unknown) => e);
        expect(err.name).toBe('ExternalAPIError');
        expect(err.message).toContain('fetch fallido');
        expect(err.message).not.toContain('10.0.0.5');
    });
    it('timeout y cancelación se distinguen en el mensaje', async () => {
        fetchMock.mockRejectedValueOnce(new DOMException('t', 'TimeoutError'));
        expect(((await researchRequest('/api/x', { timeoutMs: 777 }).catch((e: unknown) => e)) as Error).message).toContain('timeout de 777 ms');
        fetchMock.mockRejectedValueOnce(new DOMException('a', 'AbortError'));
        expect(((await researchRequest('/api/x').catch((e: unknown) => e)) as Error).message).toContain('cancelado por el llamador');
    });
    it('429 en GET reintenta una vez tras Retry-After', async () => {
        vi.useFakeTimers();
        fetchMock.mockResolvedValueOnce(res(429, {}, { 'Retry-After': '2' })).mockResolvedValueOnce(res(200, { ok: true }));
        const p = researchRequest('/api/x', { timeoutMs: 30_000 });
        await vi.advanceTimersByTimeAsync(2100);
        await expect(p).resolves.toEqual({ ok: true });
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    it('429 en POST NO reintenta (no duplicar operaciones)', async () => {
        fetchMock.mockResolvedValueOnce(res(429, { detail: 'límite' }, { 'Retry-After': '0' }));
        await expect(researchRequest('/api/x', { method: 'POST', body: '{}' })).rejects.toMatchObject({ statusCode: 429, message: 'límite' });
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    it('429 sin presupuesto restante para esperar no reintenta', async () => {
        fetchMock.mockResolvedValueOnce(res(429, {}, { 'Retry-After': '5' }));
        await expect(researchRequest('/api/x', { timeoutMs: 1000 })).rejects.toMatchObject({ statusCode: 429 });
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });
});
