import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import nextConfig from '../next.config.ts';

// Auditoría lista 8.3: la CSP servía script-src con 'unsafe-eval' también en
// producción. Ningún código de la app usa eval/new Function (grep en app/,
// components/, lib/, hooks/), así que prod ya no lo permite; dev lo mantiene
// porque webpack/turbopack usan sourcemaps basados en eval para HMR.
// 'unsafe-inline' sigue: quitarlo exige CSP con nonce vía middleware (Next
// inyecta scripts inline de bootstrap/RSC); documentado en next.config.ts.

type HeaderEntry = { key: string; value: string };

async function cspFor(nodeEnv: string): Promise<string> {
    // @types/node declara NODE_ENV como readonly; en runtime es asignable.
    const env = process.env as Record<string, string | undefined>;
    const prev = env.NODE_ENV;
    env.NODE_ENV = nodeEnv;
    try {
        const groups = await (nextConfig.headers as () => Promise<Array<{ headers: HeaderEntry[] }>>)();
        const all = groups.flatMap((g) => g.headers);
        const csp = all.find((h) => h.key === 'Content-Security-Policy');
        assert.ok(csp, 'existe el header CSP');
        return csp.value;
    } finally {
        if (prev === undefined) delete env.NODE_ENV;
        else env.NODE_ENV = prev;
    }
}

test("producción: script-src sin 'unsafe-eval'", async () => {
    const csp = await cspFor('production');
    assert.ok(!csp.includes('unsafe-eval'), csp);
    assert.match(csp, /script-src 'self' 'unsafe-inline'/);
    assert.match(csp, /default-src 'self'/);
    assert.match(csp, /frame-ancestors 'self'/);
});

test("desarrollo: se conserva 'unsafe-eval' para el HMR", async () => {
    const csp = await cspFor('development');
    assert.match(csp, /script-src 'self' 'unsafe-inline' 'unsafe-eval'/);
});

test('el resto de la política no cambia entre entornos', async () => {
    const prod = (await cspFor('production')).replace(/script-src[^;]+;/, '');
    const dev = (await cspFor('development')).replace(/script-src[^;]+;/, '');
    assert.equal(prod, dev);
});
