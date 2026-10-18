import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { RequestCache } from '../lib/cache/requestCache.ts';

// Race invalidación-repoblación (auditoría lista 9.1): invalidate() borraba
// la entrada de pendingRequests, pero el .then de la promesa en vuelo seguía
// haciendo cache.set() al resolverse: el dato obsoleto volvía a la caché
// DESPUÉS de invalidar y los siguientes get() lo servían como fresco.
// Consumidores reales: invalidatePortfolioReads (portfolio.actions.ts),
// watchlist.actions.ts y alerts.actions.ts invalidan tras mutar.

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test('invalidate() durante el vuelo: la respuesta tardía NO repuebla la caché', async () => {
    const cache = new RequestCache();
    let calls = 0;
    const fetcher = async () => {
        calls += 1;
        await tick();
        return `dato-${calls}`;
    };

    const inFlight = cache.get('k', fetcher);
    cache.invalidate('k');
    const first = await inFlight; // el awaiter recibe su dato, eso no cambia
    assert.equal(first, 'dato-1');

    // Tras invalidar, un get() debe pedir de nuevo: nada de dato-1 cacheado.
    const second = await cache.get('k', fetcher);
    assert.equal(second, 'dato-2');
    assert.equal(calls, 2);
});

test('invalidate() + nuevo get() antes de resolver: el dato viejo no pisa al nuevo', async () => {
    const cache = new RequestCache();
    let calls = 0;
    const resolvers: Array<(v: string) => void> = [];
    const fetcher = () => {
        calls += 1;
        const n = calls;
        return new Promise<string>((resolve) => resolvers.push((v) => resolve(`${v}-${n}`)));
    };

    const oldRequest = cache.get('k', fetcher);
    cache.invalidate('k');
    const newRequest = cache.get('k', fetcher);

    resolvers[1]('nuevo');
    assert.equal(await newRequest, 'nuevo-2');

    // El vuelo viejo resuelve DESPUÉS: no debe tocar caché ni pending.
    resolvers[0]('viejo');
    assert.equal(await oldRequest, 'viejo-1');

    // La caché vigente es la del fetch nuevo, no la del viejo.
    let extraCalls = 0;
    const cached = await cache.get('k', async () => {
        extraCalls += 1;
        return 'no-deberia-llamarse';
    });
    assert.equal(cached, 'nuevo-2');
    assert.equal(extraCalls, 0);
});

test('camino normal: la resolución puebla la caché y deduplica concurrentes', async () => {
    const cache = new RequestCache();
    let calls = 0;
    const fetcher = async () => {
        calls += 1;
        await tick();
        return 42;
    };
    const [a, b] = await Promise.all([cache.get('k', fetcher), cache.get('k', fetcher)]);
    assert.equal(a, 42);
    assert.equal(b, 42);
    assert.equal(calls, 1, 'deduplica peticiones concurrentes a la misma clave');
    await cache.get('k', fetcher);
    assert.equal(calls, 1, 'sirve desde caché dentro del TTL');
});

test('error en vuelo: no cachea el fallo y un invalidate() posterior es inocuo', async () => {
    const cache = new RequestCache();
    const failing = async () => {
        await tick();
        throw new Error('upstream caído');
    };
    const inFlight = cache.get('k', failing);
    cache.invalidate('k');
    await assert.rejects(inFlight, /upstream caído/);
    let okCalls = 0;
    const value = await cache.get('k', async () => {
        okCalls += 1;
        return 'recuperado';
    });
    assert.equal(value, 'recuperado');
    assert.equal(okCalls, 1);
});
