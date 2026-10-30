/**
 * Núcleo de traducción compartido por el accessor legacy (`t.ts`), el lado
 * servidor (`server.ts`) y el lado cliente (`client.tsx`).
 *
 * Cadena de resolución de una clave: diccionario del locale activo -> si la
 * clave aún no tiene traducción en ese locale, diccionario es (la referencia
 * completa) -> si tampoco existe, en desarrollo LANZA (error de programación)
 * y en producción devuelve la propia clave. Así un área en pendiente no rompe
 * pantallas: pinta el español hasta que su carril la traduzca.
 */

// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { DEFAULT_LOCALE, type Locale } from './locale.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { getMessages, type Messages } from './messages/index.ts';

export type TranslationVars = Record<string, string | number>;

/** La clave tipada vive en t.ts (TranslationKey = Leaves<typeof es>). */
import type { TranslationKey } from './t.ts';

export type TranslateFn = (path: TranslationKey, vars?: TranslationVars) => string;

function lookup(dict: Messages, path: string): unknown {
  return path
    .split('.')
    .reduce<unknown>(
      (node, key) =>
        node !== null && typeof node === 'object'
          ? (node as Record<string, unknown>)[key]
          : undefined,
      dict as unknown,
    );
}

function interpolate(template: string, path: string, vars?: TranslationVars): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const replacement = vars?.[name];
    if (replacement === undefined) {
      if (process.env.NODE_ENV !== 'production') {
        throw new Error(`[i18n] Falta la variable "{${name}}" para la clave "${path}"`);
      }
      return match;
    }
    return String(replacement);
  });
}

export function translateMessage(locale: Locale, path: string, vars?: TranslationVars): string {
  const active = getMessages(locale);
  let value = lookup(active, path);
  if (typeof value !== 'string' && locale !== DEFAULT_LOCALE) {
    // Área o clave pendiente de traducir: cae al español de referencia.
    value = lookup(getMessages(DEFAULT_LOCALE), path);
  }
  if (typeof value !== 'string') {
    if (process.env.NODE_ENV !== 'production') {
      throw new Error(`[i18n] Falta la clave "${path}" en los diccionarios (lib/i18n/messages/${DEFAULT_LOCALE}/)`);
    }
    return path;
  }
  return interpolate(value, path, vars);
}

/** t() ligada a un locale concreto (la que devuelven getT() y useT()). */
export function createTranslator(locale: Locale): TranslateFn {
  return (path, vars) => translateMessage(locale, path, vars);
}
