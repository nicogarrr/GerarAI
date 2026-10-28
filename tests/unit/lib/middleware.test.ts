// @vitest-environment node
import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { requiresSession } from '@/lib/auth/session-gate';
import { REQUESTED_PATH_HEADER } from '@/lib/auth/safe-redirect';
import { config, middleware } from '@/middleware';

function request(path: string, cookies: Record<string, string> = {}) {
    const req = new NextRequest(new URL(path, 'https://gerarai.test'));
    for (const [name, value] of Object.entries(cookies)) req.cookies.set(name, value);
    return req;
}

/** El matcher de Next es una ruta estilo path-to-regexp; anclada se comporta como aquí. */
const matcher = new RegExp(`^${config.matcher[0]}$`);

describe('middleware de sesión', () => {
    afterEach(() => {
        vi.unstubAllEnvs();
    });

    it('sin cookie de sesión redirige a /sign-in', () => {
        const res = middleware(request('/portfolio'));
        expect(res.status).toBe(307);
        expect(new URL(res.headers.get('location') ?? '').pathname).toBe('/sign-in');
    });

    it.each(['better-auth.session_token', '__Secure-better-auth.session_token'])('con cookie %s deja pasar', (name) => {
        const res = middleware(request('/portfolio', { [name]: 'tok' }));
        expect(res.headers.get('location')).toBeNull();
        expect(res.headers.get('x-middleware-next')).toBe('1');
    });

    it('con cookie anota la ruta pedida para que el layout vuelva a ella si la sesión caducó', () => {
        const res = middleware(request('/research/ASTS?tab=tesis', { 'better-auth.session_token': 'tok' }));
        expect(res.headers.get(`x-middleware-request-${REQUESTED_PATH_HEADER}`)).toBe('/research/ASTS?tab=tesis');
    });

    it('la cabecera de ruta enviada por el cliente se sobrescribe', () => {
        const req = new NextRequest(new URL('/watchlist', 'https://gerarai.test'), {
            headers: { [REQUESTED_PATH_HEADER]: '//evil.example' },
        });
        req.cookies.set('better-auth.session_token', 'tok');
        expect(middleware(req).headers.get(`x-middleware-request-${REQUESTED_PATH_HEADER}`)).toBe('/watchlist');
    });

    it('una cookie vacía no cuenta como sesión', () => {
        const res = middleware(request('/portfolio', { 'better-auth.session_token': '' }));
        expect(new URL(res.headers.get('location') ?? '').pathname).toBe('/sign-in');
    });

    it('bypass E2E solo con las TRES condiciones (como lib/auth/require-user.ts)', () => {
        vi.stubEnv('E2E_AUTH_BYPASS', '1');
        vi.stubEnv('APP_ENV', 'test');
        vi.stubEnv('NODE_ENV', 'test');
        expect(middleware(request('/portfolio')).headers.get('location')).toBeNull();

        vi.stubEnv('NODE_ENV', 'production');
        expect(middleware(request('/portfolio')).headers.get('location')).not.toBeNull();

        vi.stubEnv('NODE_ENV', 'test');
        vi.stubEnv('APP_ENV', 'development');
        expect(middleware(request('/portfolio')).headers.get('location')).not.toBeNull();

        vi.stubEnv('APP_ENV', 'test');
        vi.stubEnv('E2E_AUTH_BYPASS', '0');
        expect(middleware(request('/portfolio')).headers.get('location')).not.toBeNull();
    });

    it.each(['/', '/sign-in', '/sign-up', '/forgot-password', '/metodologia', '/help', '/privacidad', '/terminos', '/api/auth/session'])('la decisión de sesión deja pública %s', (path) => {
        expect(requiresSession(path)).toBe(false);
        expect(middleware(request(path)).headers.get('location')).toBeNull();
    });

    it.each(['/robots.txt', '/sw.js', '/manifest.webmanifest', '/_next/static/chunk.js', '/assets/icons/icon-192.png', '/investors/buffett.jpg', '/landing/ficha-movil.png'])(
        'el matcher deja pública %s',
        (path) => {
            expect(matcher.test(path)).toBe(false);
        },
    );

    it.each(['/inicio', '/portfolio', '/research/AAPL', '/taxes', '/insider', '/propicks', '/alerts'])('la decisión de sesión protege %s', (path) => {
        expect(requiresSession(path)).toBe(true);
        expect(matcher.test(path)).toBe(true);
    });
});
