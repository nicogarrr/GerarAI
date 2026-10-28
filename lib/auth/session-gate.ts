/**
 * Qué rutas exigen cookie de sesión en el middleware.
 *
 * Vive en un módulo puro (sin alias `@/`, sin APIs de Next/Node) para que el
 * guard `scripts/middleware-guard.test.ts` pruebe la decisión real y no una
 * expresión regular sobre el código fuente.
 *
 * El `matcher` del middleware es deliberadamente más ancho que esta lista:
 * también cubre las páginas públicas y `/api/*` para que TODAS las
 * respuestas HTML lleven la CSP con nonce. La decisión de sesión es esta.
 */

/**
 * Páginas que no exigen sesión. Son las mismas que el antiguo `matcher`
 * excluía del gating.
 */
const PUBLIC_PATHS = new Set([
    '/',
    '/metodologia',
    '/help',
    '/privacidad',
    '/terminos',
    '/sign-in',
    '/sign-up',
    '/forgot-password',
    '/reset-password',
]);

export function requiresSession(pathname: string): boolean {
    // Cada handler de API se autentica solo; una redirección del middleware
    // rompería los clientes de API.
    if (pathname.startsWith('/api/')) return false;
    return !PUBLIC_PATHS.has(pathname);
}
