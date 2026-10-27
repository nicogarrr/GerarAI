import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { signInUrlFor } from '@/lib/auth/safe-redirect';

/**
 * Primera línea del gating de sesión.
 *
 * Antes solo existía el corte del layout de `app/(root)/layout.tsx`: sin
 * sesión, la página autenticada arrancaba su render y su data fetching y el
 * layout redirigía después. Este middleware corta antes: sin cookie de
 * sesión, la ruta autenticada ni siquiera empieza a renderizarse.
 *
 * Lo que NO hace: validar la sesión. En el edge no hay base de datos, así
 * que aquí solo se comprueba que la cookie existe; la validez real la sigue
 * comprobando el layout (`requireAuthenticatedUser`) contra la DB. Una
 * cookie vieja pasa el middleware y el layout la redirige como hasta ahora.
 *
 * Rutas públicas intactas (ver `config.matcher`): landing `/`, `/metodologia`,
 * `/help`, `/sign-in`, `/sign-up`, `/api/*` (cada handler se autentica solo;
 * una redirección rompería los clientes de API) y los estáticos.
 */

// better-auth fija la cookie de sesión con prefijo __Secure- en HTTPS.
const SESSION_COOKIES = ['better-auth.session_token', '__Secure-better-auth.session_token'] as const;

export function middleware(request: NextRequest) {
    // Bypass de los tests de navegador: mismas tres condiciones que
    // lib/auth/require-user.ts (las tres juntas, siempre).
    if (
        process.env.E2E_AUTH_BYPASS === '1' &&
        process.env.NODE_ENV !== 'production' &&
        process.env.APP_ENV === 'test'
    ) {
        return NextResponse.next();
    }
    const hasSessionCookie = SESSION_COOKIES.some((name) => Boolean(request.cookies.get(name)?.value));
    if (!hasSessionCookie) {
        // `?next=` conserva la ruta pedida para volver a ella tras el login.
        return NextResponse.redirect(signInUrlFor(request.url));
    }
    return NextResponse.next();
}

export const config = {
    // Todo lo autenticado menos lo público. El `$` dentro del lookahead es lo
    // que deja fuera la landing (`/`): sin él `.*` casa también la cadena
    // vacía y la portada quedaría protegida.
    matcher: [
        '/((?!$|api|_next/static|_next/image|favicon.ico|sw.js|manifest.webmanifest|robots.txt|sitemap.xml|assets|investors|landing|sign-in|sign-up|forgot-password|reset-password|metodologia|help|privacidad|terminos).*)',
    ],
};
