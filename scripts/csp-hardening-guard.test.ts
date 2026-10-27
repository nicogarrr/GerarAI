import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import nextConfig from '../next.config.ts';
// @ts-expect-error -- misma razón que arriba.
import { buildContentSecurityPolicy } from '../lib/security/csp.ts';

// Auditoría: la CSP era una cabecera estática en next.config.ts y
// `script-src` necesitaba 'unsafe-inline' (Next inyecta scripts inline de
// bootstrap/RSC). Ahora el middleware genera un nonce por petición y Next lo
// estampa en sus scripts: producción no admite scripts inline sin nonce.

type HeaderEntry = { key: string; value: string };

const NONCE = 'dGVzdC1ub25jZQ==';
const PROD_CSP = buildContentSecurityPolicy(NONCE, false);
const DEV_CSP = buildContentSecurityPolicy(NONCE, true);

test("producción: script-src con nonce y strict-dynamic, sin unsafe-inline ni unsafe-eval", () => {
    assert.match(PROD_CSP, new RegExp(`script-src 'self' 'nonce-${NONCE}' 'strict-dynamic'`));
    const scriptSrc = PROD_CSP.split(';').find((d) => d.trim().startsWith('script-src')) ?? '';
    assert.ok(!scriptSrc.includes('unsafe-inline'), scriptSrc);
    assert.ok(!scriptSrc.includes('unsafe-eval'), scriptSrc);
    assert.match(PROD_CSP, /default-src 'self'/);
    assert.match(PROD_CSP, /frame-ancestors 'self'/);
});

test("desarrollo: se conservan 'unsafe-inline' y 'unsafe-eval' para el HMR", () => {
    assert.match(DEV_CSP, /script-src 'self' 'unsafe-inline' 'unsafe-eval'/);
});

test('el resto de la política no cambia entre entornos', () => {
    const stripScriptSrc = (csp: string) => csp.replace(/script-src[^;]+;/, '');
    assert.equal(stripScriptSrc(PROD_CSP), stripScriptSrc(DEV_CSP));
});

test("ambos entornos: object-src 'none' (sin plugins ni <object>/<embed>)", () => {
    for (const csp of [PROD_CSP, DEV_CSP]) {
        assert.match(csp, /object-src 'none'/);
    }
});

test("style-src mantiene 'unsafe-inline' (estilos inline de React/Tailwind)", () => {
    for (const csp of [PROD_CSP, DEV_CSP]) {
        assert.match(csp, /style-src 'self' 'unsafe-inline'/);
    }
});

test('next.config.ts ya no fija CSP (la fija el middleware; dos políticas se acumularían)', async () => {
    const groups = await (nextConfig.headers as () => Promise<Array<{ headers: HeaderEntry[] }>>)();
    const all = groups.flatMap((g) => g.headers);
    assert.ok(!all.some((h) => h.key === 'Content-Security-Policy'), 'next.config.ts no debe emitir CSP');
});

test('el middleware genera el nonce por petición y fija la CSP en petición y respuesta', () => {
    const source = readFileSync('middleware.ts', 'utf8');
    assert.match(source, /buildContentSecurityPolicy\(nonce/);
    assert.match(source, /requestHeaders\.set\('Content-Security-Policy', csp\)/);
    assert.match(source, /response\.headers\.set\('Content-Security-Policy', csp\)/);
    assert.match(source, /requestHeaders\.set\('x-nonce', nonce\)/);
});

test('la app no tiene scripts inline que noncear (SW registration es componente cliente)', () => {
    assert.ok(!readFileSync('app/layout.tsx', 'utf8').includes('dangerouslySetInnerHTML'), 'app/layout.tsx');
});

async function headerFor(key: string): Promise<string | undefined> {
    const groups = await (nextConfig.headers as () => Promise<Array<{ headers: HeaderEntry[] }>>)();
    return groups.flatMap((g) => g.headers).find((h) => h.key === key)?.value;
}

test('cabeceras de aislamiento y endurecimiento presentes', async () => {
    assert.equal(await headerFor('Cross-Origin-Opener-Policy'), 'same-origin');
    assert.equal(await headerFor('X-Content-Type-Options'), 'nosniff');
    assert.equal(await headerFor('X-Frame-Options'), 'SAMEORIGIN');
    assert.match((await headerFor('Strict-Transport-Security')) ?? '', /max-age=\d{8,}/);
});
