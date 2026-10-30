/**
 * i18n para server components y server actions.
 *
 * `getLocale()` lee la cookie `gerarai_locale` de la request (memoizada por
 * request con React `cache`, sin estado global mutable). `getT()` y
 * `getFormat()` devuelven las utilidades ligadas a ese locale:
 *
 *   const t = await getT();
 *   const fmt = await getFormat();
 *
 * Solo importable desde código de servidor: usa next/headers.
 */

import { cache } from 'react';
import { cookies } from 'next/headers';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createFormatters, type Formatters } from '../format.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { LOCALE_COOKIE, parseLocale, type Locale } from './locale.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { createTranslator, type TranslateFn } from './translate.ts';

/** Locale de la request actual (cookie `gerarai_locale`; por defecto `es`). */
export const getLocale = cache(async (): Promise<Locale> => {
  const store = await cookies();
  return parseLocale(store.get(LOCALE_COOKIE)?.value);
});

/** t() ligada al locale de la request. */
export async function getT(): Promise<TranslateFn> {
  return createTranslator(await getLocale());
}

/** Funciones de formato (números, fechas, importes) ligadas al locale. */
export async function getFormat(): Promise<Formatters> {
  return createFormatters(await getLocale());
}
