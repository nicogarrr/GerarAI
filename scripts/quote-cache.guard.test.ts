/**
 * Guarda de la caché de cotizaciones públicas (lib/market/quote-cache.ts):
 * TTL y revalidación por reloj, anti-estampida (Retry-After/backoff),
 * dedupe, saturación degradada SIN fanout, timeout y rechazo con cleanup,
 * maps acotados, claves normalizadas y robustez numérica.
 * Todo con reloj inyectable y fetcher ficticio: CERO red real.
 *
 * Ejecución: node --experimental-strip-types --test scripts/quote-cache.guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { getEventListeners } from 'node:events';

register('./manual-demo-guard.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
const { createQuoteCache, combineAbortSignals } = await import('../lib/market/quote-cache.ts');
// @ts-expect-error TS5097
const { classifyQuoteKind } = await import('../lib/market/quote-freshness.ts');

const T0 = 1_760_000_000_000; // reloj fijo de fixture (ms epoch)
const SEC = 1000;

/** Cotización saneada mínima con t (segundos) configurable. */
const quote = (tSeconds: number, c = 10) => ({ source: 'Finnhub', c, d: 0, dp: 0, h: c, l: c, o: c, pc: c, t: tSeconds, kind: 'live' });

/** Reloj manual + fetcher contador configurable. */
function rig(behavior: (symbol: string, calls: number) => Promise<{ quote: unknown; fetchFailed: boolean; retryAfterSeconds: number | null }>, opts: Record<string, number> = {}) {
    let nowMs = T0;
    const calls: string[] = [];
    const cache = createQuoteCache({ now: () => nowMs, ...opts });
    const fetcher = async (symbol: string) => {
        calls.push(symbol);
        return behavior(symbol, calls.length) as never;
    };
    return { cache, fetcher, calls, advance: (ms: number) => { nowMs += ms; }, now: () => nowMs };
}

const ok = (tSeconds: number, c = 10) => ({ quote: quote(tSeconds, c), fetchFailed: false, retryAfterSeconds: null });
const fail = (retryAfterSeconds: number | null = null) => ({ quote: null, fetchFailed: true, retryAfterSeconds });

describe('caché de cotizaciones públicas', () => {
    it('dentro del TTL: un solo fetch y mismo fetchedAt; expirado el TTL: refetch', async () => {
        const { cache, fetcher, calls, advance } = rig(async () => ok(Math.floor(T0 / SEC)));
        const r1 = await cache.getQuote('BBVA', fetcher);
        assert.equal(r1.quote?.c, 10);
        assert.equal(r1.fetchedAt, T0);
        assert.equal(r1.saturated, false);
        advance(5_000);
        const r2 = await cache.getQuote('BBVA', fetcher);
        assert.equal(calls.length, 1, 'sin fetch nuevo dentro del TTL');
        assert.equal(r2.fetchedAt, T0, 'fetchedAt conserva cuándo salió del proveedor');
        advance(20_001);
        const r3 = await cache.getQuote('BBVA', fetcher);
        assert.equal(calls.length, 2, 'expirado el TTL se repide');
        assert.equal(r3.fetchedAt, T0 + 25_001);
    });

    it('revalidación por reloj: una cotización que cruza a stale DENTRO del TTL se descarta y se repide', async () => {
        // Frontera real con el clasificador de verdad: quote fija no-stale
        // en t0 que pasa a stale al avanzar el reloj (apertura de sesión).
        const qT = Math.floor(T0 / SEC) - 12 * 3600;
        let boundary: number | null = null;
        for (let probe = T0; probe < T0 + 10 * 86_400_000; probe += 5 * 60_000) {
            const before = classifyQuoteKind(qT, probe);
            const after = classifyQuoteKind(qT, probe + 5 * 60_000);
            if (before !== 'stale' && after === 'stale') {
                boundary = probe + 5 * 60_000;
                break;
            }
        }
        assert.ok(boundary !== null, 'la fixture necesita una frontera de sesión en 10 días');
        const { cache, fetcher, calls, advance } = rig(async () => ok(qT));
        advance(boundary - 10_000 - T0); // 10 s antes de la frontera
        const r1 = await cache.getQuote('S', fetcher);
        assert.equal(r1.quote !== null, true, 'cotización válida antes de la frontera');
        assert.equal(calls.length, 1);
        advance(15_000); // cruza la frontera, DENTRO del TTL de 20 s
        const r2 = await cache.getQuote('S', fetcher);
        assert.equal(calls.length, 2, 'la cotización envejecida no se sirve: se repide pese al TTL');
        assert.equal(r2.quote !== null, true);
    });

    it('una cotización ya stale NO se cachea (defensa del settle)', async () => {
        const ancient = Math.floor(T0 / SEC) - 10 * 86_400;
        const { cache, fetcher, calls } = rig(async () => ok(ancient));
        const r1 = await cache.getQuote('OLD', fetcher);
        assert.equal(r1.quote !== null, true, 'el dato llega al llamador (la decisión de usarlo es suya)');
        const r2 = await cache.getQuote('OLD', fetcher);
        assert.equal(r2.quote !== null, true);
        assert.equal(calls.length, 2, 'pero nunca se cachea: cada llamada reintenta');
        assert.equal(cache.size(), 0);
    });

    it('429 con Retry-After: no cachea valor, frena reintentos y respeta la espera', async () => {
        let mode: 'fail' | 'ok' = 'fail';
        const { cache, fetcher, calls, advance } = rig(async (_s) => (mode === 'fail' ? fail(120) : ok(Math.floor(T0 / SEC) + 130)));
        const r1 = await cache.getQuote('X', fetcher);
        assert.equal(r1.fetchFailed, true);
        assert.equal(r1.retryAfterSeconds, 120);
        advance(30_000);
        const r2 = await cache.getQuote('X', fetcher);
        assert.equal(calls.length, 1, 'sin reintento durante la ventana Retry-After');
        assert.equal(r2.fetchFailed, true);
        assert.equal(r2.retryAfterSeconds, 90, 'la espera restante se descuenta');
        mode = 'ok';
        advance(91_000);
        const r3 = await cache.getQuote('X', fetcher);
        assert.equal(calls.length, 2, 'cumplida la espera se reintenta');
        assert.equal(r3.quote !== null, true);
    });

    it('fallo de red sin Retry-After: backoff exponencial acotado, sin estampida', async () => {
        const { cache, fetcher, calls, advance } = rig(async () => fail(null));
        await cache.getQuote('Y', fetcher); // fallo 1 → notBefore +1s
        advance(500);
        await cache.getQuote('Y', fetcher);
        assert.equal(calls.length, 1, 'dentro del backoff no hay fetch');
        advance(600); // +1.1s → reintento
        await cache.getQuote('Y', fetcher); // fallo 2 → notBefore +2s
        assert.equal(calls.length, 2);
        advance(1_500);
        await cache.getQuote('Y', fetcher);
        assert.equal(calls.length, 2, 'el backoff crece (2s) y frena el tercer intento');
    });

    it('éxito tras fallo limpia el backoff y cachea con normalidad', async () => {
        let mode: 'fail' | 'ok' = 'fail';
        const { cache, fetcher, calls, advance, now } = rig(async (_s) => (mode === 'fail' ? fail(null) : ok(Math.floor(now() / SEC))));
        await cache.getQuote('Z', fetcher); // fallo → backoff 1s
        advance(1_100);
        mode = 'ok';
        const r = await cache.getQuote('Z', fetcher);
        assert.equal(r.quote !== null, true);
        assert.equal(cache.failureSize(), 0, 'marca limpiada');
        const okCalls = calls.length;
        advance(5_000); // dentro del TTL
        await cache.getQuote('Z', fetcher);
        assert.equal(calls.length, okCalls, 'el éxito queda cacheado con normalidad');
    });

    it('dedupe: dos llamadas concurrentes al mismo símbolo comparten UN fetch', async () => {
        let release: (v: ReturnType<typeof ok>) => void = () => {};
        const gate = new Promise<ReturnType<typeof ok>>((res) => { release = res; });
        const { cache, fetcher, calls } = rig(() => gate as never);
        const p1 = cache.getQuote('D', fetcher);
        const p2 = cache.getQuote('D', fetcher);
        await new Promise((r) => setTimeout(r, 10));
        assert.equal(calls.length, 1, 'un solo fetch en curso para ambas');
        release(ok(Math.floor(T0 / SEC)));
        const [r1, r2] = await Promise.all([p1, p2]);
        assert.equal(r1.quote?.c, 10);
        assert.equal(r2.quote?.c, 10);
    });

    it('saturación: ráfaga > maxInflight degrada SIN fetch nuevo y sin fanout', async () => {
        const nowMs = T0;
        const calls: string[] = [];
        const pending: Array<() => void> = [];
        const cache = createQuoteCache({ now: () => nowMs, maxInflight: 2 });
        const fetcher = (symbol: string) => {
            calls.push(symbol);
            // A y B quedan en vuelo; C (degradada primero, repedida al final) resuelve ya.
            if (symbol === 'C') return Promise.resolve(ok(Math.floor(nowMs / SEC)) as never);
            return new Promise<never>((res) => pending.push(() => res(ok(Math.floor(nowMs / SEC)) as never)));
        };
        const p1 = cache.getQuote('A', fetcher);
        const p2 = cache.getQuote('B', fetcher);
        await new Promise((r) => setTimeout(r, 10));
        const r3 = await cache.getQuote('C', fetcher); // mapa lleno → degradado
        assert.deepEqual(calls.sort(), ['A', 'B'], 'C NO lanza fetch: la ráfaga no abre fanout');
        assert.equal(r3.saturated, true, 'degradado explícito y distinguible');
        assert.equal(r3.quote, null, 'no se maquilla dato viejo como reciente');
        assert.equal(r3.fetchFailed, true);
        assert.equal(r3.fetchedAt, null);
        for (const release of pending) release();
        const [r1, r2] = await Promise.all([p1, p2]);
        assert.equal(r1.quote !== null && r2.quote !== null, true, 'los en curso terminan con dato');
        assert.equal(cache.inflightSize(), 0, 'inflight drenado');
        const r4 = await cache.getQuote('C', fetcher);
        assert.equal(r4.saturated, false, 'tras drenar, el símbolo degradado se pide con normalidad');
        assert.equal(r4.quote !== null, true);
    });

    it('rechazo del fetcher: resultado de fallo (sin excepción), cleanup de inflight y marca', async () => {
        let mode: 'throw' | 'ok' = 'throw';
        const { cache, fetcher, calls, advance, now } = rig(async (_s) => {
            if (mode === 'throw') throw new Error('red caída');
            return ok(Math.floor(now() / SEC));
        });
        const p1 = cache.getQuote('R', fetcher);
        const p2 = cache.getQuote('R', fetcher); // comparte el fetch que va a rechazar
        const [r1, r2] = await Promise.all([p1, p2]);
        assert.equal(r1.fetchFailed, true, 'el rechazo se convierte en fallo, no en excepción');
        assert.equal(r2.fetchFailed, true, 'los que compartían el inflight reciben el mismo fallo');
        assert.equal(calls.length, 1, 'un solo fetch pese al rechazo compartido');
        assert.equal(cache.inflightSize(), 0, 'inflight limpio tras rechazo');
        assert.equal(cache.failureSize(), 1, 'backoff anotado');
        advance(1_100);
        mode = 'ok';
        const r3 = await cache.getQuote('R', fetcher);
        assert.equal(r3.quote !== null, true, 'cumplido el backoff se reintenta y funciona');
        assert.equal(calls.length, 2);
    });

    it('timeout del fetcher: fallo acotado, cleanup, y la respuesta tardía NO se cachea', async (t) => {
        let lateRelease: (v: ReturnType<typeof ok>) => void = () => {};
        const realNow = Date.now();
        let phase: 'hang' | 'ok' = 'hang';
        const calls: string[] = [];
        const cache = createQuoteCache({ fetchTimeoutMs: 60 });
        const fetcher = (symbol: string) => {
            calls.push(symbol);
            if (phase === 'hang') {
                return new Promise<never>((res) => { lateRelease = res as never; });
            }
            return Promise.resolve(ok(Math.floor(Date.now() / SEC)) as never);
        };
        // Keep-alive: el timer de timeout va unref (correcto en producción);
        // sin otro handle el runner vería el event loop vacío antes de disparar.
        const keepAlive = setInterval(() => {}, 25);
        t.after(() => clearInterval(keepAlive));
        const r1 = await cache.getQuote('T', fetcher); // cuelga → timeout ~60 ms reales
        assert.equal(r1.fetchFailed, true, 'el timeout se sirve como fallo');
        assert.equal(cache.inflightSize(), 1, 'el slot real se conserva mientras el fetch sigue vivo');
        lateRelease(ok(Math.floor(realNow / SEC))); // la respuesta tardía llega después
        await new Promise((r) => setTimeout(r, 20));
        assert.equal(cache.inflightSize(), 0, 'slot liberado al asentar de verdad');
        assert.equal(cache.size(), 0, 'la respuesta tardía no se cachea');
        phase = 'ok';
        // Tras el backoff del timeout (1s real), el símbolo se puede repedir.
        await new Promise((r) => setTimeout(r, 1_100));
        const r2 = await cache.getQuote('T', fetcher);
        assert.equal(calls.length, 2, 'nuevo fetch real tras el timeout');
        assert.equal(r2.quote !== null, true);
    });

    it('timeout con fetcher que HONORA la señal: abort llega al fetch y el slot se libera al asentar', async (t) => {
        const keepAlive = setInterval(() => {}, 25);
        t.after(() => clearInterval(keepAlive));
        let realActive = 0;
        let maxRealActive = 0;
        let sawAbort = false;
        const calls: string[] = [];
        const cache = createQuoteCache({ fetchTimeoutMs: 60, maxInflight: 1 });
        const fetcher = (symbol: string, signal: AbortSignal) => {
            calls.push(symbol);
            realActive += 1;
            maxRealActive = Math.max(maxRealActive, realActive);
            return new Promise<never>((resolve) => {
                signal.addEventListener('abort', () => {
                    sawAbort = true;
                    realActive -= 1;
                    resolve({ quote: null, fetchFailed: true, retryAfterSeconds: null } as never); // asienta al abortar
                });
            });
        };
        const r1 = await cache.getQuote('SIG', fetcher); // cuelga → timeout ~60 ms → abort
        assert.equal(r1.fetchFailed, true);
        assert.equal(sawAbort, true, 'la señal de cancelación llegó al fetcher');
        await new Promise((r) => setTimeout(r, 20));
        assert.equal(cache.inflightSize(), 0, 'slot liberado al asentar (abortó)');
        assert.equal(maxRealActive, 1, 'nunca más de 1 operación real activa');
        assert.equal(calls.length, 1);
    });

    it('timeout con fetcher que IGNORA la señal: el zombi conserva el slot y no hay solape', async (t) => {
        const keepAlive = setInterval(() => {}, 25);
        t.after(() => clearInterval(keepAlive));
        let realActive = 0;
        let maxRealActive = 0;
        const calls: string[] = [];
        // Backoff base 1 ms: la marca del propio timeout expira al instante y
        // no tapa la saturación, que es lo que se mide aquí.
        const cache = createQuoteCache({ fetchTimeoutMs: 60, maxInflight: 1, failureBackoffBaseMs: 1 });
        let phase: 'zombie' | 'ok' = 'zombie';
        const fetcher = (symbol: string, _signal: AbortSignal) => {
            calls.push(symbol);
            if (phase === 'ok') return Promise.resolve(ok(Math.floor(Date.now() / 1000)) as never);
            realActive += 1;
            maxRealActive = Math.max(maxRealActive, realActive);
            // Ignora la señal: asienta 300 ms después pase lo que pase.
            return new Promise<never>((resolve) =>
                setTimeout(() => {
                    realActive -= 1;
                    resolve(ok(Math.floor(Date.now() / 1000)) as never);
                }, 300),
            );
        };
        const r1 = await cache.getQuote('ZB', fetcher); // timeout a ~60 ms; el zombi sigue vivo
        assert.equal(r1.fetchFailed, true);
        assert.equal(cache.inflightSize(), 1, 'el zombi conserva su slot real');
        await new Promise((r) => setTimeout(r, 60)); // t≈120 ms: zombi aún vivo
        const r2 = await cache.getQuote('ZB', fetcher);
        assert.equal(r2.saturated, true, 'sin fetch nuevo mientras el zombi ocupa el slot');
        assert.equal(calls.length, 1, 'ninguna operación nueva: cero solape');
        assert.equal(cache.size(), 0, 'la respuesta tardía del zombi no se cacheará');
        await new Promise((r) => setTimeout(r, 260)); // t≈380 ms: zombi asentado
        assert.equal(cache.inflightSize(), 0, 'slot liberado tras asentamiento real');
        assert.equal(cache.size(), 0, 'el éxito tardío del zombi NO se cacheó');
        phase = 'ok';
        const r3 = await cache.getQuote('ZB', fetcher);
        assert.equal(r3.saturated, false);
        assert.equal(r3.quote !== null, true, 'liberado el slot se trabaja con normalidad');
        assert.equal(calls.length, 2);
        assert.equal(maxRealActive, 1, 'jamás hubo 2 operaciones reales a la vez');
    });

    it('bound de entradas: al superarlo se expulsa la más vieja (fetchedAt)', async () => {
        let nowMs = T0;
        const calls: string[] = [];
        const cache = createQuoteCache({ now: () => nowMs, maxEntries: 2 });
        const fetcher = async (symbol: string) => {
            calls.push(symbol);
            return ok(Math.floor(nowMs / SEC)) as never;
        };
        await cache.getQuote('K1', fetcher);
        nowMs += 1_000;
        await cache.getQuote('K2', fetcher);
        nowMs += 1_000;
        await cache.getQuote('K3', fetcher);
        assert.equal(cache.size(), 2, 'nunca más entradas que el bound');
        nowMs += 1_000;
        await cache.getQuote('K1', fetcher);
        assert.deepEqual(calls, ['K1', 'K2', 'K3', 'K1'], 'la más vieja se expulsó y se repide');
        calls.length = 0;
        await cache.getQuote('K3', fetcher);
        assert.deepEqual(calls, [], 'K3 sobrevivió: sigue servida desde caché');
        await cache.getQuote('K2', fetcher);
        assert.deepEqual(calls, ['K2'], 'K2 quedó expulsada por la reentrada de K1');
    });

    it('mapa de marcas acotado: al superarlo se expulsa la que expira antes', async () => {
        let failsLeft = 2; // solo los dos primeros fetches fallan; la repesca de M1 tiene éxito
        const { cache, fetcher, calls, advance, now } = rig(async (_s) => {
            if (failsLeft-- > 0) return fail(null);
            return ok(Math.floor(now() / SEC));
        }, { maxFailureMarks: 1 });
        await cache.getQuote('M1', fetcher); // marca M1 (+1s)
        advance(100);
        await cache.getQuote('M2', fetcher); // bound 1 → expulsa M1, marca M2
        assert.equal(cache.failureSize(), 1, 'nunca más marcas que el bound');
        calls.length = 0;
        await cache.getQuote('M1', fetcher);
        assert.deepEqual(calls, ['M1'], 'M1 perdió su marca: vuelve a pedir enseguida');
        calls.length = 0;
        await cache.getQuote('M2', fetcher);
        assert.deepEqual(calls, [], 'M2 sigue frenada por su marca');
    });

    it('claves normalizadas: espacios y mayúsculas comparten caché y fetch', async () => {
        const { cache, fetcher, calls } = rig(async () => ok(Math.floor(T0 / SEC)));
        await cache.getQuote(' bbva ', fetcher);
        await cache.getQuote('BBVA', fetcher);
        await cache.getQuote('BbVa', fetcher);
        assert.deepEqual(calls, ['BBVA'], 'una sola clave canónica');
    });

    it('símbolo vacío tras normalizar: error explícito', async () => {
        const { cache, fetcher } = rig(async () => ok(Math.floor(T0 / SEC)));
        assert.throws(() => cache.getQuote('   ', fetcher), TypeError);
    });

    it('robustez numérica: opciones basura caen a defectos y el backoff nunca es Infinity', async () => {
        let nowMs = T0;
        const calls: string[] = [];
        const cache = createQuoteCache({
            now: () => nowMs,
            ttlMs: Infinity,
            maxEntries: NaN,
            maxInflight: -5,
            fetchTimeoutMs: Number.POSITIVE_INFINITY,
        });
        const fetcher = async (symbol: string) => {
            calls.push(symbol);
            return fail(null) as never;
        };
        await cache.getQuote('F', fetcher);
        // ttlMs Infinity → defecto 20 s: el backoff (1s) caduca y refetcha.
        nowMs += 1_100;
        await cache.getQuote('F', fetcher);
        assert.equal(calls.length, 2, 'los defectos rigen pese a opciones basura');
        // 40 fallos seguidos: la espera anunciada queda finita y topada.
        let lastRetry = 0;
        for (let i = 0; i < 40; i++) {
            nowMs += 61_000; // más que el tope de backoff (60 s)
            const r = await cache.getQuote('F', fetcher);
            if (r.fetchFailed && r.retryAfterSeconds !== null) lastRetry = r.retryAfterSeconds;
        }
        assert.ok(Number.isFinite(lastRetry) && lastRetry <= 60, `backoff finito y topado (último: ${lastRetry}s)`);
    });

    it('null saneado sin fetchFailed (dato viejo/ausente): ni valor ni marca; reintento inmediato', async () => {
        const { cache, fetcher, calls } = rig(async () => ({ quote: null, fetchFailed: false, retryAfterSeconds: null }));
        await cache.getQuote('N', fetcher);
        await cache.getQuote('N', fetcher);
        assert.equal(calls.length, 2, 'un dato ausente no se cachea ni frena reintentos');
        assert.equal(cache.failureSize(), 0);
    });
});

describe('combineAbortSignals (fallback compatible sin AbortSignal.any)', () => {
    const combine = combineAbortSignals as (external: AbortSignal, timeoutMs: number) => AbortSignal;
    const anyDesc = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
    const sinAny = <T>(fn: () => T): T => {
        (AbortSignal as unknown as { any?: unknown }).any = undefined;
        try {
            return fn();
        } finally {
            if (anyDesc) Object.defineProperty(AbortSignal, 'any', anyDesc);
        }
    };

    it('ruta nativa (any presente): el abort externo se propaga con su reason', () => {
        const c = new AbortController();
        const combined = combine(c.signal, 60_000);
        c.abort('motivo-externo');
        assert.equal(combined.aborted, true);
        assert.equal(combined.reason, 'motivo-externo');
    });

    it('fallback sin any: abort externo => combinada abortada, reason preservado y listeners retirados', () => {
        sinAny(() => {
            const c = new AbortController();
            const combined = combine(c.signal, 60_000);
            assert.equal(getEventListeners(c.signal, 'abort').length, 1, 'escuchando la fuente externa');
            c.abort('motivo-externo');
            assert.equal(combined.aborted, true, 'la cancelación externa es real sin any');
            assert.equal(combined.reason, 'motivo-externo');
            assert.equal(getEventListeners(c.signal, 'abort').length, 0, 'no retiene la cadena tras abortar');
        });
    });

    it('fallback sin any: el timeout propio también aborta de verdad', async () => {
        await sinAny(async () => {
            const c = new AbortController();
            const combined = combine(c.signal, 30);
            assert.equal(combined.aborted, false);
            await new Promise((r) => setTimeout(r, 80));
            assert.equal(combined.aborted, true, 'el tope interno aborta sin any');
            assert.equal((combined.reason as { name?: string })?.name, 'TimeoutError');
            assert.equal(getEventListeners(c.signal, 'abort').length, 0, 'listeners retirados tras el timeout');
        });
    });

    it('fallback sin any: señal YA abortada => combinada abortada al instante, sin listeners', () => {
        sinAny(() => {
            const c = new AbortController();
            c.abort('ya-abortada');
            const combined = combine(c.signal, 60_000);
            assert.equal(combined.aborted, true);
            assert.equal(combined.reason, 'ya-abortada');
            assert.equal(getEventListeners(c.signal, 'abort').length, 0, 'no registra listeners innecesarios');
        });
    });
});
