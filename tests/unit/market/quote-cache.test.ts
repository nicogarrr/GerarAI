// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';

import { combineAbortSignals, createQuoteCache, type QuoteFetchAttempt } from '@/lib/market/quote-cache';
import { classifyQuoteKind, type SanitizedQuote } from '@/lib/market/quote-freshness';

// Miércoles 28-oct-2026 11:00 ET (EDT, UTC-4): sesión US abierta.
const OPEN_MS = Date.UTC(2026, 9, 28, 15, 0, 0);

const quote = (nowMs: number, c = 100): SanitizedQuote => ({
    source: 'Finnhub', c, d: 1, dp: 1, h: c + 1, l: c - 1, o: c, pc: c - 1, t: Math.floor(nowMs / 1000), kind: 'live',
});
const ok = (nowMs: number, c = 100): QuoteFetchAttempt => ({ quote: quote(nowMs, c), fetchFailed: false, retryAfterSeconds: null });
const fail = (retryAfterSeconds: number | null = null): QuoteFetchAttempt => ({ quote: null, fetchFailed: true, retryAfterSeconds });

function clock(start = OPEN_MS) {
    let t = start;
    return { now: () => t, advance: (ms: number) => { t += ms; } };
}

describe('classifyQuoteKind (base del cache)', () => {
    it('sesión abierta + t dentro de la sesión = live', () => {
        expect(classifyQuoteKind(OPEN_MS / 1000 - 60, OPEN_MS)).toBe('live');
    });
    it('un dato de hace una semana durante la sesión es stale', () => {
        expect(classifyQuoteKind(OPEN_MS / 1000 - 7 * 86400, OPEN_MS)).toBe('stale');
    });
});

describe('createQuoteCache - aciertos y TTL', () => {
    it('sirve desde caché dentro del TTL con UN solo fetch y devuelve el fetchedAt real', async () => {
        const c = clock();
        const cache = createQuoteCache({ ttlMs: 20_000, now: c.now });
        const fetcher = vi.fn(async () => ok(c.now()));
        const first = await cache.getQuote('aapl', fetcher);
        c.advance(5_000);
        const second = await cache.getQuote('  AAPL ', fetcher);
        expect(fetcher).toHaveBeenCalledTimes(1);
        expect(fetcher).toHaveBeenCalledWith('AAPL', expect.any(AbortSignal));
        expect(second.quote?.c).toBe(100);
        expect(second.fetchedAt).toBe(first.fetchedAt);
        expect(second.fetchedAt).toBe(OPEN_MS);
        expect(cache.size()).toBe(1);
    });

    it('pasado el TTL vuelve a pedir y actualiza el precio', async () => {
        const c = clock();
        const cache = createQuoteCache({ ttlMs: 20_000, now: c.now });
        const fetcher = vi.fn(async () => ok(c.now(), c.now() === OPEN_MS ? 100 : 105));
        await cache.getQuote('MSFT', fetcher);
        c.advance(20_001);
        const again = await cache.getQuote('MSFT', fetcher);
        expect(fetcher).toHaveBeenCalledTimes(2);
        expect(again.quote?.c).toBe(105);
    });

    it('rechaza un símbolo vacío tras normalizar', () => {
        const cache = createQuoteCache();
        expect(() => cache.getQuote('   ', async () => fail())).toThrow(TypeError);
    });

    it('un dato que envejece a stale dentro del TTL no se sirve: se re-pide', async () => {
        const c = clock();
        const cache = createQuoteCache({ ttlMs: 10 * 86400_000, now: c.now });
        const fetcher = vi.fn(async () => ok(c.now()));
        await cache.getQuote('NVDA', fetcher);
        c.advance(8 * 86400_000); // 8 días: ya es stale aunque el TTL no haya vencido
        await cache.getQuote('NVDA', fetcher);
        expect(fetcher).toHaveBeenCalledTimes(2);
    });
});

describe('createQuoteCache - dedupe y saturación', () => {
    it('llamadas concurrentes al mismo símbolo comparten un fetch', async () => {
        const c = clock();
        const cache = createQuoteCache({ now: c.now });
        let release!: (a: QuoteFetchAttempt) => void;
        const fetcher = vi.fn(() => new Promise<QuoteFetchAttempt>((r) => { release = r; }));
        const a = cache.getQuote('TSLA', fetcher);
        const b = cache.getQuote('tsla', fetcher);
        expect(cache.inflightSize()).toBe(1);
        await Promise.resolve(); await Promise.resolve(); // el fetcher se invoca en un microtask
        release(ok(c.now(), 250));
        const [ra, rb] = await Promise.all([a, b]);
        expect(fetcher).toHaveBeenCalledTimes(1);
        expect(ra).toEqual(rb);
        expect(cache.inflightSize()).toBe(0);
    });

    it('al saturar maxInflight devuelve resultado degradado SIN fetch nuevo y distinguible', async () => {
        const c = clock();
        const cache = createQuoteCache({ maxInflight: 1, now: c.now });
        let release!: (a: QuoteFetchAttempt) => void;
        const slow = vi.fn(() => new Promise<QuoteFetchAttempt>((r) => { release = r; }));
        const first = cache.getQuote('AAA', slow);
        await Promise.resolve(); await Promise.resolve();
        const other = vi.fn(async () => ok(c.now()));
        const degraded = await cache.getQuote('BBB', other);
        expect(other).not.toHaveBeenCalled();
        expect(degraded).toEqual({ quote: null, fetchFailed: true, retryAfterSeconds: null, fetchedAt: null, saturated: true });
        release(ok(c.now()));
        await first;
        await new Promise((r) => setTimeout(r, 0)); // el slot se libera en el finally, tras resolver
        // Con el slot libre, BBB ya puede pedir.
        expect((await cache.getQuote('BBB', other)).saturated).toBe(false);
        expect(other).toHaveBeenCalledTimes(1);
    });
});

describe('createQuoteCache - fallos sin envenenar', () => {
    it('un fallo no cachea valor y activa backoff exponencial acotado', async () => {
        const c = clock();
        const cache = createQuoteCache({ now: c.now, failureBackoffBaseMs: 1_000, failureBackoffCapMs: 4_000 });
        const fetcher = vi.fn(async () => fail());
        const r1 = await cache.getQuote('X', fetcher);
        expect(r1).toMatchObject({ quote: null, fetchFailed: true, saturated: false });
        expect(cache.size()).toBe(0);
        expect(cache.failureSize()).toBe(1);
        // Dentro de la ventana (1 s): no se vuelve a llamar al proveedor.
        c.advance(400);
        const inWindow = await cache.getQuote('X', fetcher);
        expect(fetcher).toHaveBeenCalledTimes(1);
        expect(inWindow.fetchFailed).toBe(true);
        expect(inWindow.retryAfterSeconds).toBe(1); // ceil(600ms)
        // Tras la ventana, segundo fallo: espera 2 s; tercero 4 s; cuarto sigue en el tope de 4 s.
        c.advance(700);
        await cache.getQuote('X', fetcher); // fallo 2 -> 2 s
        c.advance(1_500);
        expect((await cache.getQuote('X', fetcher)).fetchFailed).toBe(true);
        expect(fetcher).toHaveBeenCalledTimes(2);
        c.advance(600);
        await cache.getQuote('X', fetcher); // fallo 3 -> 4 s
        c.advance(4_001);
        await cache.getQuote('X', fetcher); // fallo 4 -> tope 4 s, no 8 s
        c.advance(3_999);
        await cache.getQuote('X', fetcher); // aún dentro de la ventana de 4 s
        expect(fetcher).toHaveBeenCalledTimes(4);
        c.advance(2);
        await cache.getQuote('X', fetcher);
        expect(fetcher).toHaveBeenCalledTimes(5);
    });

    it('respeta Retry-After del proveedor, acotado por maxRetryAfterSeconds', async () => {
        const c = clock();
        const cache = createQuoteCache({ now: c.now, maxRetryAfterSeconds: 60 });
        const fetcher = vi.fn(async () => fail(3600));
        const first = await cache.getQuote('R', fetcher);
        expect(first.retryAfterSeconds).toBe(60);
        c.advance(59_000);
        expect((await cache.getQuote('R', fetcher)).retryAfterSeconds).toBe(1);
        expect(fetcher).toHaveBeenCalledTimes(1);
        c.advance(1_001);
        await cache.getQuote('R', fetcher);
        expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it('un éxito posterior borra la marca de fallo', async () => {
        const c = clock();
        const cache = createQuoteCache({ now: c.now });
        await cache.getQuote('S', async () => fail());
        expect(cache.failureSize()).toBe(1);
        c.advance(2_000);
        const good = await cache.getQuote('S', async () => ok(c.now()));
        expect(good.quote).not.toBeNull();
        expect(cache.failureSize()).toBe(0);
    });

    it('un rechazo del fetcher se convierte en fallo, no en excepción', async () => {
        const cache = createQuoteCache({ now: clock().now });
        const r = await cache.getQuote('Z', async () => { throw new Error('boom'); });
        expect(r).toMatchObject({ quote: null, fetchFailed: true });
    });

    it('un fetcher que devuelve undefined cuenta como fallo', async () => {
        const cache = createQuoteCache({ now: clock().now });
        const r = await cache.getQuote('U', (async () => undefined) as unknown as () => Promise<QuoteFetchAttempt>);
        expect(r.fetchFailed).toBe(true);
    });

    it('nunca cachea una cotización ya stale', async () => {
        const c = clock();
        const cache = createQuoteCache({ now: c.now });
        const old: QuoteFetchAttempt = { quote: quote(c.now() - 7 * 86400_000), fetchFailed: false, retryAfterSeconds: null };
        const r = await cache.getQuote('OLD', async () => old);
        expect(cache.size()).toBe(0);
        expect(cache.failureSize()).toBe(0); // dato viejo no es fallo del proveedor: se reintenta enseguida
        expect(r.fetchFailed).toBe(false);
    });

    it('timeout: libera al llamador, aborta la señal y no cachea la respuesta tardía', async () => {
        vi.useFakeTimers();
        try {
            const c = clock();
            const cache = createQuoteCache({ now: c.now, fetchTimeoutMs: 50 });
            let signal!: AbortSignal;
            let late!: (a: QuoteFetchAttempt) => void;
            const fetcher = (_s: string, sig: AbortSignal) => { signal = sig; return new Promise<QuoteFetchAttempt>((r) => { late = r; }); };
            const p = cache.getQuote('T', fetcher);
            await vi.advanceTimersByTimeAsync(60);
            const r = await p;
            expect(r).toMatchObject({ quote: null, fetchFailed: true });
            expect(signal.aborted).toBe(true);
            // El slot sigue ocupado hasta que el fetcher asienta de verdad (zombi).
            expect(cache.inflightSize()).toBe(1);
            late(ok(c.now(), 999));
            await vi.advanceTimersByTimeAsync(0);
            expect(cache.inflightSize()).toBe(0);
            expect(cache.size()).toBe(0); // la respuesta tardía no se cachea
        } finally {
            vi.useRealTimers();
        }
    });
});

describe('createQuoteCache - límites de memoria y opciones basura', () => {
    it('expulsa la entrada más vieja al superar maxEntries', async () => {
        const c = clock();
        const cache = createQuoteCache({ maxEntries: 2, now: c.now });
        for (const s of ['A', 'B', 'C']) {
            await cache.getQuote(s, async () => ok(c.now()));
            c.advance(10);
        }
        expect(cache.size()).toBe(2);
        const fetcher = vi.fn(async () => ok(c.now()));
        await cache.getQuote('A', fetcher); // A fue expulsada: vuelve a pedir
        expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it('acota las marcas de fallo a maxFailureMarks', async () => {
        const c = clock();
        const cache = createQuoteCache({ maxFailureMarks: 2, now: c.now });
        for (const s of ['A', 'B', 'C', 'D']) await cache.getQuote(s, async () => fail());
        expect(cache.failureSize()).toBe(2);
    });

    it('opciones basura (NaN, Infinity, negativos) caen a defectos finitos y el reloj NaN a Date.now', async () => {
        const cache = createQuoteCache({
            ttlMs: Number.NaN, maxEntries: -5, maxInflight: Infinity, fetchTimeoutMs: 0,
            maxFailureMarks: Number.NaN, maxRetryAfterSeconds: -1, failureBackoffBaseMs: 0, failureBackoffCapMs: Infinity,
            now: () => Number.NaN,
        });
        const r = await cache.getQuote('N', async () => fail(-3));
        expect(r.fetchFailed).toBe(true);
        expect(cache.failureSize()).toBe(1);
        expect(r.retryAfterSeconds).toBeNull(); // retryAfter negativo se descarta
    });
});

describe('combineAbortSignals', () => {
    it('aborta cuando aborta la señal externa', () => {
        const ext = new AbortController();
        const sig = combineAbortSignals(ext.signal, 60_000);
        expect(sig.aborted).toBe(false);
        ext.abort();
        expect(sig.aborted).toBe(true);
    });
    it('una señal externa ya abortada produce una señal abortada', () => {
        expect(combineAbortSignals(AbortSignal.abort(), 60_000).aborted).toBe(true);
    });
    it('sin AbortSignal.any usa el controlador manual y aborta desde cualquiera de las fuentes', () => {
        const any = AbortSignal.any;
        // @ts-expect-error forzar la rama de compatibilidad
        AbortSignal.any = undefined;
        try {
            const ext = new AbortController();
            const s1 = combineAbortSignals(ext.signal, 60_000);
            ext.abort(new Error('x'));
            expect(s1.aborted).toBe(true);
            expect(combineAbortSignals(AbortSignal.abort(), 60_000).aborted).toBe(true);
            const s3 = combineAbortSignals(new AbortController().signal, 1);
            return new Promise<void>((resolve) => setTimeout(() => { expect(s3.aborted).toBe(true); resolve(); }, 30));
        } finally {
            AbortSignal.any = any;
        }
    });
});
