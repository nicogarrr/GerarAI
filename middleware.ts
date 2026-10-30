import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { REQUESTED_PATH_HEADER, signInUrlFor } from '@/lib/auth/safe-redirect';
import { requiresSession } from '@/lib/auth/session-gate';
import { buildContentSecurityPolicy } from '@/lib/security/csp';
import { legacyResearchRedirect } from '@/lib/research/research-views';

/**
 * Dos responsabilidades por petición, en este orden:
 *
 * 1. CSP con nonce (todas las rutas que casan el `matcher`, públicas o no).
 *    Se genera un nonce aleatorio por petición y se fija la cabecera
 *    `Content-Security-Policy` en la RESPUESTA y en la PETICIÓN reescrita:
 *    Next lee la de la petición durante el render y estampa ese nonce en sus
 *    scripts inline de bootstrap/RSC, así `script-src` ya no necesita
 *    'unsafe-inline' en producción. El nonce también queda en `x-nonce` por
 *    si algún Server Component lo necesita (`headers().get('x-nonce')`).
 *
 * 2. Gating de sesión (solo rutas autenticadas). Primera línea del corte:
 *    sin cookie de sesión, la ruta autenticada ni siquiera empieza a
 *    renderizarse. Lo que NO hace: validar la sesión. En el edge no hay base
 *    de datos, así que aquí solo se comprueba que la cookie existe; la
 *    validez real la sigue comprobando el layout (`requireAuthenticatedUser`)
 *    contra la DB. Una cookie vieja pasa el middleware y el layout la
 *    redirige como hasta ahora.
 *
 * Rutas públicas intactas (ver `lib/auth/session-gate.ts`): landing `/`,
 * `/metodologia`, `/help`, `/sign-in`, `/sign-up`, `/api/*` (cada handler se
 * autentica solo; una redirección rompería los clientes de API) y los
 * estáticos, que ni siquiera entran al middleware (`config.matcher`).
 */

// better-auth fija la cookie de sesión con prefijo __Secure- en HTTPS.
const SESSION_COOKIES = ['better-auth.session_token', '__Secure-better-auth.session_token'] as const;

export function middleware(request: NextRequest) {
    // Buffer existe en el runtime edge del middleware (polyfill de Next); es
    // la forma documentada por Next para el nonce de la CSP.
    const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
    const csp = buildContentSecurityPolicy(nonce, process.env.NODE_ENV !== 'production');

    const requestHeaders = new Headers(request.headers);
    requestHeaders.set('x-nonce', nonce);
    requestHeaders.set('Content-Security-Policy', csp);
    // `x-requested-path` conserva la ruta pedida para volver a ella tras el
    // login: con cookie pero sesión caducada, quien redirige al login es el
    // layout (`redirectToSignIn`), y sin esta cabecera no sabría a dónde
    // volver. Se sobrescribe siempre: lo que mande el cliente no llega.
    requestHeaders.set(REQUESTED_PATH_HEADER, `${request.nextUrl.pathname}${request.nextUrl.search}`);

    // URLs históricas de la ficha de empresa (?view=thesis, /share-capital…):
    // 307 real, ANTES de renderizar. En page.tsx el redirect() saltaba con la
    // carcasa de loading.tsx ya enviada y React la degradaba a redirección de
    // cliente («Switched to client rendering»): sin JS la ficha se quedaba en
    // «Cargando…» para siempre (E2E de hidratación, 30-oct-2026).
    const researchTarget = legacyResearchRedirect(request.nextUrl.pathname, request.nextUrl.search);
    if (researchTarget) {
        const redirect = NextResponse.redirect(new URL(researchTarget, request.url), 307);
        redirect.headers.set('Content-Security-Policy', csp);
        return redirect;
    }

    // Bypass de los tests de navegador: mismas tres condiciones que
    // lib/auth/require-user.ts (las tres juntas, siempre).
    const e2eBypass =
        process.env.E2E_AUTH_BYPASS === '1' &&
        process.env.NODE_ENV !== 'production' &&
        process.env.APP_ENV === 'test';

    if (!e2eBypass && requiresSession(request.nextUrl.pathname)) {
        const hasSessionCookie = SESSION_COOKIES.some((name) => Boolean(request.cookies.get(name)?.value));
        if (!hasSessionCookie) {
            // `?next=` conserva la ruta pedida para volver a ella tras el login.
            const redirect = NextResponse.redirect(signInUrlFor(request.url));
            redirect.headers.set('Content-Security-Policy', csp);
            return redirect;
        }
    }

    const response = NextResponse.next({ request: { headers: requestHeaders } });
    response.headers.set('Content-Security-Policy', csp);
    return response;
}

export const config = {
    // Todo menos los estáticos puros: la CSP con nonce aplica también a la
    // landing, las páginas públicas y `/api/*`; el gating de sesión decide
    // por ruta en `requiresSession`. Los ficheros de `public/` (assets,
    // investors, landing) y los de metadata no necesitan CSP ni middleware.
    matcher: [
        '/((?!_next/static|_next/image|favicon.ico|sw.js|manifest.webmanifest|robots.txt|sitemap.xml|assets|investors|landing).*)',
    ],
};
