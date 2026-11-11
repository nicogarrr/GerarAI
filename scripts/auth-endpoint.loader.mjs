export async function resolve(specifier, context, nextResolve) {
    if (specifier === '@/lib/better-auth/auth') return { url: 'auth-endpoint:auth', shortCircuit: true };
    if (specifier === 'next/headers') return { url: 'auth-endpoint:next', shortCircuit: true };
    if (specifier === '@/lib/types/errors') return { url: new URL('../lib/types/errors.ts', import.meta.url).href, shortCircuit: true };
    if (specifier === '@/lib/auth/signup-policy') return { url: new URL('../lib/auth/signup-policy.ts', import.meta.url).href, shortCircuit: true };
    if (specifier === '@/lib/auth/account-approval') return { url: new URL('../lib/auth/account-approval.ts', import.meta.url).href, shortCircuit: true };
    if (specifier === '@/lib/auth/legal-acceptance') return { url: new URL('../lib/auth/legal-acceptance.ts', import.meta.url).href, shortCircuit: true };
    if (specifier === '@/lib/i18n/server') return { url: new URL('./auth-session-boundary.i18n-shim.mjs', import.meta.url).href, shortCircuit: true };
    return nextResolve(specifier, context);
}
export async function load(url, context, nextLoad) {
    const sources = {
        'auth-endpoint:auth': 'export async function getAuth() { return globalThis.__endpointAuth; }',
        'auth-endpoint:next': 'export async function headers() { return globalThis.__endpointHeaders; } export async function cookies() { return { set: (...args) => globalThis.__endpointCookies.push(args) }; }',
    };
    if (url in sources) return { format: 'module', source: sources[url], shortCircuit: true };
    return nextLoad(url, context);
}
