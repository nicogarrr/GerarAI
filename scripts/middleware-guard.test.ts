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

    it('el matcher excluye login, páginas públicas, API y estáticos', () => {
        const matcher = mw.match(/matcher:\s*\[\s*'([^']+)'/)?.[1];
        assert.ok(matcher, 'config.matcher no encontrado');
        for (const pub of ['sign-in', 'sign-up', 'metodologia', 'help', 'api', '_next/static', '_next/image', 'favicon.ico', 'sw.js', 'manifest.webmanifest', 'robots.txt', 'sitemap.xml', 'assets']) {
            assert.ok(matcher.includes(pub), `el matcher debe excluir ${pub}`);
        }
        // La exclusión es un negative lookahead tras '/(': si se pierde el
        // formato, el matcher deja de excluir y rompe login y estáticos.
        assert.match(matcher, /^\/\(\(\?!/);
    });

    it('la landing (/) queda pública y las rutas autenticadas protegidas (simulación del matcher)', () => {
        const matcher = mw.match(/matcher:\s*\[\s*'([^']+)'/)?.[1] ?? '';
        const re = new RegExp('^' + matcher + '$');
        for (const pub of ['/', '/sign-in', '/sign-up', '/metodologia', '/help', '/api/auth/session', '/robots.txt', '/sw.js', '/assets/icons/icon-192.png', '/investors/buffett.jpg', '/landing/ficha-movil.png']) {
            assert.equal(re.test(pub), false, `${pub} debe quedar pública`);
        }
        for (const priv of ['/inicio', '/taxes', '/insider', '/movers', '/research/AAPL', '/propicks', '/portfolio']) {
            assert.equal(re.test(priv), true, `${priv} debe quedar protegida`);
        }
    });
});
