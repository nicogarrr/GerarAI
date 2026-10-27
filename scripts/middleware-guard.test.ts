/**
 * Guard: existe un middleware de sesión y no rompe lo público ni el login.
 *
 * Antes el único corte era el layout de (root): la página autenticada
 * arrancaba su render/data fetching sin sesión. El middleware exige cookie
 * de sesión en las rutas autenticadas, respeta las públicas, las de auth y
 * el bypass E2E (mismas tres condiciones que lib/auth/require-user.ts).
 *
 * Ejecución: node --experimental-strip-types --test scripts/middleware-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { requiresSession } from '../lib/auth/session-gate.ts';

describe('middleware de sesión', () => {
    it('existe en la raíz del repo', () => {
        assert.ok(existsSync('middleware.ts'), 'falta middleware.ts en la raíz');
    });
    const mw = readFileSync('middleware.ts', 'utf8');

    it('exige cookie de sesión (normal y __Secure-) y redirige a /sign-in', () => {
        assert.match(mw, /better-auth\.session_token/);
        assert.match(mw, /__Secure-better-auth\.session_token/);
        assert.match(mw, /NextResponse\.redirect\(signInUrlFor\(request\.url\)\)/);
    });

    it('respeta el bypass E2E con las tres condiciones de require-user', () => {
        assert.match(mw, /process\.env\.E2E_AUTH_BYPASS === '1'/);
        assert.match(mw, /process\.env\.NODE_ENV !== 'production'/);
        assert.match(mw, /process\.env\.APP_ENV === 'test'/);
    });

    it('el matcher solo excluye estáticos (la CSP con nonce aplica a todo lo demás)', () => {
        const matcher = mw.match(/matcher:\s*\[\s*'([^']+)'/)?.[1];
        assert.ok(matcher, 'config.matcher no encontrado');
        for (const pub of ['_next/static', '_next/image', 'favicon.ico', 'sw.js', 'manifest.webmanifest', 'robots.txt', 'sitemap.xml', 'assets', 'investors', 'landing']) {
            assert.ok(matcher.includes(pub), `el matcher debe excluir ${pub}`);
        }
        // La exclusión es un negative lookahead tras '/(': si se pierde el
        // formato, el matcher deja de excluir y los estáticos pasan por el
        // middleware.
        assert.match(matcher, /^\/\(\(\?!/);
        // Las páginas públicas y la API ya NO se excluyen en el matcher: la
        // CSP también las cubre; la sesión la decide requiresSession.
        for (const notExcluded of ['api', 'sign-in', 'metodologia', 'help']) {
            assert.ok(!matcher.includes(notExcluded), `el matcher ya no excluye ${notExcluded}`);
        }
    });

    it('los estáticos no pasan por el middleware y el resto sí (simulación del matcher)', () => {
        const matcher = mw.match(/matcher:\s*\[\s*'([^']+)'/)?.[1] ?? '';
        const re = new RegExp('^' + matcher + '$');
        for (const stat of ['/robots.txt', '/sw.js', '/manifest.webmanifest', '/sitemap.xml', '/favicon.ico', '/assets/icons/icon-192.png', '/investors/buffett.jpg', '/landing/ficha-movil.png']) {
            assert.equal(re.test(stat), false, `${stat} debe quedar fuera del middleware`);
        }
        for (const covered of ['/', '/sign-in', '/metodologia', '/help', '/api/auth/session', '/inicio', '/research/AAPL']) {
            assert.equal(re.test(covered), true, `${covered} debe pasar por el middleware (CSP)`);
        }
    });

    it('la decisión de sesión respeta lo público y protege lo autenticado (requiresSession real)', () => {
        for (const pub of ['/', '/sign-in', '/sign-up', '/forgot-password', '/reset-password', '/metodologia', '/help', '/privacidad', '/terminos', '/api/auth/session', '/api/health']) {
            assert.equal(requiresSession(pub), false, `${pub} debe quedar pública`);
        }
        for (const priv of ['/inicio', '/taxes', '/insider', '/movers', '/research/AAPL', '/propicks', '/portfolio']) {
            assert.equal(requiresSession(priv), true, `${priv} debe quedar protegida`);
        }
    });
});
