// Loader para la prueba con MongoDB replica set REAL (mongodb-memory-server):
// mismo código final de las acciones; solo se sustituyen auth (stub) y la
// conexión (apunta al RS efímero). Modelo y paper-trading van al fuente real.
const REAL = {
    '@/database/models/manual-demo.model': '../database/models/manual-demo.model.ts',
    '@/lib/paper-trading/types': '../lib/paper-trading/types.ts',
    '@/lib/paper-trading/accounting': '../lib/paper-trading/accounting.ts',
    '@/lib/paper-trading/options': '../lib/paper-trading/options.ts',
    '@/lib/paper-trading/ledger-adapter': '../lib/paper-trading/ledger-adapter.ts',
    '@/database/mongoose': './real-rs-conn.mjs',
    '@/lib/market/quote-freshness': '../lib/market/quote-freshness.ts',
    '@/lib/market/demo-valuation': '../lib/market/demo-valuation.ts',
};
const AUTH_STUB = [
    'export async function requireAuthenticatedUser() {',
    '    const u = globalThis.__MANUAL_DEMO_GUARD_USER__;',
    "    if (!u) { const e = new Error('User not authenticated'); e.name = 'AuthenticationError'; throw e; }",
    '    return u;',
    '}',
].join('\n');
export async function resolve(specifier, context, nextResolve) {
    if (specifier === 'mongoose' && !String(context.parentURL ?? '').endsWith('real-rs-mongoose-shim.mjs')) {
        return { url: new URL('./real-rs-mongoose-shim.mjs', import.meta.url).href, shortCircuit: true };
    }
    if (specifier === '@/lib/auth/require-user') return { url: 'guard-stub:require-user', shortCircuit: true };
    if (REAL[specifier]) return { url: new URL(REAL[specifier], import.meta.url).href, shortCircuit: true };
    if (specifier.startsWith('@/')) throw new Error(`real-rs loader: import no esperado: ${specifier}`);
    return nextResolve(specifier, context);
}
export async function load(url, context, nextLoad) {
    if (url === 'guard-stub:require-user') return { format: 'module', shortCircuit: true, source: AUTH_STUB };
    return nextLoad(url, context);
}
