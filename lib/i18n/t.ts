/**
 * i18n del repo: diccionarios por área en messages/<locale>/<area>.json y un
 * accessor con tipos.
 *
 * Por qué NO next-intl: no hay enrutado por locale y la carga de mensajes por
 * request con un `NextIntlClientProvider` precargado no aporta nada aquí. Un
 * registro de JSON + una función tipada por `typeof es` da lo mismo
 * (autocompletado de claves y error de compilación si la clave no existe) sin
 * dependencias.
 *
 * Este módulo es el accessor LEGACY síncrono, fijado al locale por defecto
 * (es): existe para que las llamadas `t()` antiguas sigan compilando mientras
 * los carriles migran. Código nuevo:
 * - server components: `const t = await getT()` de `@/lib/i18n/server`;
 * - client components: `const t = useT()` de `@/lib/i18n/client`.
 *
 * Módulo puro: se importa igual desde server y client components.
 */

// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { DEFAULT_LOCALE } from './locale.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { messages } from './messages/index.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { translateMessage, type TranslationVars } from './translate.ts';

/** Diccionario de referencia (locale por defecto). */
export const es = messages.es;

export type { TranslationVars };

type Leaves<T> = T extends string
  ? ''
  : {
      [K in keyof T & string]: T[K] extends string ? K : `${K}.${Leaves<T[K]>}`;
    }[keyof T & string];

/** Claves aceptadas: "portfolio.tearsheet.maxDrawdown" (hoja del diccionario). */
export type TranslationKey = Leaves<typeof es>;

/**
 * Traduce una clave del diccionario EN ESPAÑOL (locale por defecto).
 *
 * - Sustituye `{name}` por los valores de `vars`.
 * - En DESARROLLO lanza si la clave no existe o falta una variable: es un
 *   error de programación y debe verse en la consola, no como `{n}` en
 *   pantalla ni como un "N/D" silencioso.
 * - En PRODUCCIÓN devuelve la propia clave: la UI se mantiene legible y no se
 *   rompe la página por un texto que falta.
 */
export function t(path: TranslationKey, vars?: TranslationVars): string {
  return translateMessage(DEFAULT_LOCALE, path, vars);
}
