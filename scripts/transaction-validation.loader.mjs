/**
 * Loader de soporte SOLO para transaction-validation.test.ts.
 *
 * node --experimental-strip-types no resuelve el alias `@/` de tsconfig.
 * Redirige `@/lib/format` al fichero REAL del repo (misma estrategia que
 * research-identity-guard.loader.mjs): el código bajo test es el fuente
 * real, sin copiar ni reescribir.
 */
export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@/lib/format') {
    return {
      url: new URL('../lib/format.ts', import.meta.url).href,
      shortCircuit: true,
    };
  }
  if (specifier === '@/lib/i18n/parse-number') {
    return {
      url: new URL('../lib/i18n/parse-number.ts', import.meta.url).href,
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}
