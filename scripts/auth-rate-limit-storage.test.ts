import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { betterAuth } from 'better-auth';
import { memoryAdapter } from 'better-auth/adapters/memory';
// @ts-expect-error TS5097: node strip-types needs the source extension.
const { buildAuthRateLimit } = await import('../lib/better-auth/rate-limit.ts');

// Los contadores de login de Better Auth tienen que vivir en la base de datos
// compartida: en Vercel cada instancia tenia su propio Map en memoria y el
// limite de intentos se multiplicaba por el numero de instancias.

const prod = { NODE_ENV: 'production' };

test('con base de datos el limite de auth se guarda en ella; sin ella, en memoria', () => {
    assert.equal(buildAuthRateLimit({ hasDatabase: true, env: prod }).storage, 'database');
    assert.equal(buildAuthRateLimit({ hasDatabase: false, env: prod }).storage, 'memory');
    assert.equal(buildAuthRateLimit({ hasDatabase: true, env: prod }).enabled, true);
    assert.equal(buildAuthRateLimit({ hasDatabase: true, env: { NODE_ENV: 'development' } }).enabled, false);
    assert.equal(buildAuthRateLimit({ hasDatabase: true, env: { AUTH_RATE_LIMIT_ENABLED: 'true' } }).enabled, true);
});

test('los intentos de login fallidos quedan en la coleccion rateLimit y el cuarto recibe 429', async () => {
    const db: Record<string, Array<Record<string, unknown>>> = { user: [], session: [], account: [], verification: [], rateLimit: [] };
    const options = {
        database: memoryAdapter(db),
        secret: 'synthetic-only-test-'.repeat(3),
        baseURL: 'http://localhost:3000',
        emailAndPassword: { enabled: true },
        rateLimit: buildAuthRateLimit({ hasDatabase: true, env: prod }),
    };
    // Dos "instancias" que comparten base de datos, como dos funciones de Vercel.
    const instances = [betterAuth(options), betterAuth(options)];
    const statuses: number[] = [];
    for (let i = 0; i < 4; i += 1) {
        const response = await instances[i % 2].handler(new Request('http://localhost:3000/api/auth/sign-in/email', {
            method: 'POST',
            headers: { 'content-type': 'application/json', origin: 'http://localhost:3000', 'x-forwarded-for': '203.0.113.90' },
            body: JSON.stringify({ email: 'nobody@example.com', password: 'wrong-password-123' }),
        }));
        statuses.push(response.status);
    }
    assert.deepEqual(statuses.slice(0, 3).map(s => s !== 429), [true, true, true]);
    assert.equal(statuses[3], 429);
    const row = db.rateLimit.find(r => String(r.key).startsWith('203.0.113.90|'));
    assert.ok(row, 'el contador de intentos debe estar en la base de datos compartida');
    assert.equal(row.count, 3);
});

test('auth.ts usa la configuracion compartida y le dice si hay base de datos', () => {
    const source = readFileSync(new URL('../lib/better-auth/auth.ts', import.meta.url), 'utf8');
    assert.match(source, /rateLimit:\s*buildAuthRateLimit\(\{\s*hasDatabase:\s*Boolean\(database\)/);
});
