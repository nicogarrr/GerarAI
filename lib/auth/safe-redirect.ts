/**
 * Destino tras iniciar sesión.
 *
 * Antes el middleware mandaba a `/sign-in` sin recordar la ruta pedida y el
 * formulario hacía siempre `router.push('/inicio')`: un enlace a
 * `/research/ASTS` (un aviso de Telegram, un marcador, una pestaña con la
 * sesión caducada) acababa en Inicio después de entrar y había que volver a
 * buscar la ficha.
 *
 * Ahora el middleware añade `?next=<ruta>` y la página de login lo sanea con
 * `safeInternalPath` antes de usarlo: solo rutas internas del propio sitio
 * (nada de `//otro.dominio`, `/\otro`, `https://…` ni caracteres de control),
 * para no abrir una redirección abierta.
 *
 * Módulo puro (sin alias `@/` ni APIs de Node): lo usan el middleware (edge),
 * la página de login y el guard de `node --test`.
 */

export const DEFAULT_AFTER_SIGN_IN = '/inicio';

const MAX_NEXT_LENGTH = 2048;

/** Páginas de acceso: volver a ellas tras entrar sería un bucle. */
const AUTH_PATHS = new Set(['/sign-in', '/sign-up', '/forgot-password', '/reset-password']);

const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

const PLACEHOLDER_ORIGIN = 'http://gerarai.invalid';

export function safeInternalPath(raw: unknown, fallback: string = DEFAULT_AFTER_SIGN_IN): string {
    const value = Array.isArray(raw) ? raw[0] : raw;
    if (typeof value !== 'string' || value.length === 0 || value.length > MAX_NEXT_LENGTH) return fallback;
    // Ruta relativa a la raíz y nada más: `//host` y `/\host` los navegadores
    // los interpretan como otro dominio.
    if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return fallback;
    if (CONTROL_CHARS.test(value)) return fallback;
    try {
        if (CONTROL_CHARS.test(decodeURIComponent(value))) return fallback;
        const url = new URL(value, PLACEHOLDER_ORIGIN);
        if (url.origin !== PLACEHOLDER_ORIGIN) return fallback;
        if (AUTH_PATHS.has(url.pathname)) return fallback;
        return `${url.pathname}${url.search}${url.hash}`;
    } catch {
        return fallback;
    }
}

/** URL de `/sign-in` para una petición sin sesión, con `?next=` si aporta algo. */
export function signInUrlFor(requestUrl: string): URL {
    const requested = new URL(requestUrl);
    const signIn = new URL('/sign-in', requested);
    const next = safeInternalPath(`${requested.pathname}${requested.search}`);
    if (next !== DEFAULT_AFTER_SIGN_IN) {
        signIn.searchParams.set('next', next);
    }
    return signIn;
}

/**
 * Cabecera interna con la ruta pedida (`pathname + search`). La pone el
 * middleware en la petición; los layouts y páginas de servidor no conocen su
 * URL, así que sin ella una sesión caducada (cookie presente pero inválida)
 * mandaba a `/sign-in` a secas y, tras entrar, se caía en /inicio.
 * El middleware la sobrescribe siempre: un valor enviado por el cliente no
 * llega, y aun así se sanea con `safeInternalPath`.
 */
export const REQUESTED_PATH_HEADER = 'x-gerarai-requested-path';

/** Ruta relativa de `/sign-in`, con `?next=` cuando la ruta pedida es interna y aporta algo. */
export function signInPathFor(requestedPath: unknown): string {
    const next = safeInternalPath(requestedPath);
    if (next === DEFAULT_AFTER_SIGN_IN) return '/sign-in';
    return `/sign-in?${new URLSearchParams({ next }).toString()}`;
}
