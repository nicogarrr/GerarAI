/**
 * Loader de soporte SOLO para research-identity-guard.test.ts.
 *
 * node --experimental-strip-types no resuelve el alias `@/` de tsconfig
 * ni debe arrancar el runtime Next (`next/headers` via require-user).
 * Este loader redirige:
 * - `@/lib/auth/require-user` -> stub inline con usuario fijo (equivale a
 *   la semantica de E2E_AUTH_BYPASS=1: identidad fija de test, sin sesion).
 * - `@/lib/types/errors` -> fichero REAL del repo.
 *
 * Todo el codigo bajo test (HMAC, nonce, canonicalizacion, body-hash) es
 * el fuente real de lib/auth/research-identity.ts, sin copiar ni reescribir.
 */
export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@/lib/auth/require-user') {
    return { url: 'guard-stub:require-user', shortCircuit: true };
  }
  if (specifier === '@/lib/types/errors') {
    return {
      url: new URL('../lib/types/errors.ts', import.meta.url).href,
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  if (url === 'guard-stub:require-user') {
    return {
      format: 'module',
      source: [
        'export async function requireAuthenticatedUser() {',
        "  return { id: 'guard-test-user', email: 'guard@gerarai.test', name: 'Guard' };",
        '}',
      ].join('\n'),
      shortCircuit: true,
    };
  }
  return nextLoad(url, context);
}
