// Isolate Next/DB dependencies only. The actions under test are the real source.
export async function resolve(specifier, context, nextResolve) {
    if (specifier === '@/lib/auth/endpoint') return { url: 'auth-boundary:endpoint', shortCircuit: true };
    if (specifier === '@/lib/better-auth/auth') return { url: 'auth-boundary:auth', shortCircuit: true };
    if (specifier === 'next/headers') return { url: 'auth-boundary:headers', shortCircuit: true };
    if (specifier === '@/lib/types/errors') return { url: new URL('../lib/types/errors.ts', import.meta.url).href, shortCircuit: true };
    if (specifier === '@/lib/auth/endpoint-messages') return { url: new URL('../lib/auth/endpoint-messages.ts', import.meta.url).href, shortCircuit: true };
    if (specifier === '@/lib/constants') return { url: 'auth-boundary:constants', shortCircuit: true };
    if (specifier === '@/lib/i18n/server') return { url: new URL('./auth-session-boundary.i18n-shim.mjs', import.meta.url).href, shortCircuit: true };
    return nextResolve(specifier, context);
}
export async function load(url, context, nextLoad) {
    const sources = {
        'auth-boundary:endpoint': `export async function callAuthEndpoint(path, body) { const names = { '/sign-in/email': 'signInEmail', '/sign-up/email': 'signUpEmail', '/two-factor/verify-totp': 'verifyTOTP' }; if (globalThis.__authBoundaryEndpointError) throw globalThis.__authBoundaryEndpointError; return globalThis.__authBoundaryTestAuth.api[names[path]]({ body }); }`,
        'auth-boundary:auth': 'export async function getAuth() { return globalThis.__authBoundaryTestAuth; }',
        'auth-boundary:headers': 'export async function headers() { return new Headers(); }',
        'auth-boundary:constants': 'export const ERROR_MESSAGES = { AUTH_UNAVAILABLE: "No disponible", AUTH_FAILED: "No autenticado" };',
    };
    if (url in sources) return { format: 'module', source: sources[url], shortCircuit: true };
    return nextLoad(url, context);
}
