/**
 * Enlace profundo tras el login: sin sesión, /research/ASTS (p. ej. desde un
 * aviso de Telegram) manda a /sign-in y, al entrar, se vuelve a esa ruta en
 * lugar de caer siempre en /inicio. Sin redirecciones abiertas.
 * Ejecución: node --experimental-strip-types --test scripts/auth-safe-redirect.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { DEFAULT_AFTER_SIGN_IN, safeInternalPath, signInUrlFor } from '../lib/auth/safe-redirect.ts';

describe('safeInternalPath', () => {
    it('acepta rutas internas con query y hash', () => {
        assert.equal(safeInternalPath('/research/ASTS'), '/research/ASTS');
        assert.equal(safeInternalPath('/research/CGEO.L/valuation?tab=dcf#escenarios'), '/research/CGEO.L/valuation?tab=dcf#escenarios');
        assert.equal(safeInternalPath(['/watchlist', '/otra']), '/watchlist');
    });

    it('cae en /inicio ante valores ausentes o externos (sin redirección abierta)', () => {
        for (const bad of [undefined, null, '', 42, 'https://evil.example', '//evil.example', '/\\evil.example', '/\\/evil', 'javascript:alert(1)', 'research/ASTS', ' /inicio', '/%0d%0aSet-Cookie:x', '/a\nb', '/' + 'x'.repeat(3000)]) {
            assert.equal(safeInternalPath(bad), DEFAULT_AFTER_SIGN_IN, String(bad).slice(0, 40));
        }
    });

    it('no devuelve a las páginas de acceso (evita bucles)', () => {
        for (const loop of ['/sign-in', '/sign-in?next=/x', '/sign-up', '/forgot-password', '/reset-password?token=a']) {
            assert.equal(safeInternalPath(loop), DEFAULT_AFTER_SIGN_IN, loop);
        }
    });
});

describe('signInUrlFor', () => {
    it('conserva ruta y query en ?next=', () => {
        const url = signInUrlFor('http://127.0.0.1:3200/research/ASTS?tab=tesis');
        assert.equal(url.pathname, '/sign-in');
        assert.equal(url.searchParams.get('next'), '/research/ASTS?tab=tesis');
        assert.equal(url.origin, 'http://127.0.0.1:3200');
    });

    it('sin destino útil, /sign-in limpio', () => {
        assert.equal(signInUrlFor('http://127.0.0.1:3200/inicio').search, '');
    });
});

describe('cableado', () => {
    it('el middleware redirige con signInUrlFor', () => {
        const mw = readFileSync('middleware.ts', 'utf8');
        assert.match(mw, /NextResponse\.redirect\(signInUrlFor\(request\.url\)\)/);
    });

    it('la página de login sanea ?next= y el formulario navega a ese destino', () => {
        const page = readFileSync('app/(auth)/sign-in/page.tsx', 'utf8');
        assert.match(page, /safeInternalPath\(/);
        const form = readFileSync('components/forms/SignInForm.tsx', 'utf8');
        assert.match(form, /router\.push\(redirectTo\)/);
        assert.doesNotMatch(form, /router\.push\('\/inicio'\)/);
    });
});
