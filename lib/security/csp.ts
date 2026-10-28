/**
 * Content-Security-Policy con nonce por petición.
 *
 * Hasta aquí la CSP vivía en `next.config.ts` como cabecera estática y
 * `script-src` necesitaba 'unsafe-inline': Next inyecta scripts inline de
 * bootstrap/RSC y una cabecera fija no puede noncearlos. Con el nonce
 * generado en `middleware.ts` (una cadena aleatoria por petición, en la
 * cabecera CSP de la petición y de la respuesta) Next estampa ese nonce en
 * sus propios scripts y 'unsafe-inline' desaparece de producción: un script
 * inline inyectado por XSS ya no ejecuta aunque llegue al DOM.
 *
 * 'strict-dynamic' delega la confianza: los chunks que el bootstrap de Next
 * carga dinámicamente heredan la confianza del script nonceado que los pide,
 * sin lista de hosts que mantener. En navegadores antiguos sin soporte se
 * ignora y manda 'self'.
 *
 * En desarrollo se conserva la política anterior: el HMR de webpack/turbopack
 * usa sourcemaps basados en eval ('unsafe-eval') y scripts inline
 * ('unsafe-inline'), y el nonce no aporta nada contra amenazas en local.
 *
 * 'unsafe-inline' en style-src se mantiene en ambos entornos: React/Tailwind
 * emite estilos inline (atributo style) y nonces de estilo no cubren ese
 * caso. El riesgo residual es bajo: sin 'unsafe-inline' en script-src no hay
 * ejecución vía CSS inyectado.
 *
 * Módulo puro (sin alias `@/` ni APIs de Node/Next): lo usan el middleware
 * (edge) y el guard `scripts/csp-hardening-guard.test.ts` (node --test).
 */
export function buildContentSecurityPolicy(nonce: string, isDev: boolean): string {
    const scriptSrc = isDev
        ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
        : `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`;
    return [
        "default-src 'self'",
        scriptSrc,
        "style-src 'self' 'unsafe-inline'",
        'img-src \'self\' data: https:',
        "font-src 'self' data:",
        "connect-src 'self' https:",
        'frame-src https://www.youtube-nocookie.com https://www.youtube.com',
        "frame-ancestors 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ].join('; ');
}
