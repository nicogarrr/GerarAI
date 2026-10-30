/**
 * Locales soportados y la cookie que fija el idioma de la interfaz.
 *
 * Módulo puro (sin React ni next/headers): se importa igual desde server,
 * client y scripts. El selector de idioma está en Ajustes y escribe la
 * cookie `gerarai_locale`; no hay prefijos de URL por idioma.
 */

export const SUPPORTED_LOCALES = ['es', 'en'] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

/** Idioma por defecto cuando no hay cookie o su valor no es válido. */
export const DEFAULT_LOCALE: Locale = 'es';

/** Cookie de preferencia de idioma (la lee el servidor en cada request). */
export const LOCALE_COOKIE = 'gerarai_locale';

/** Locale Intl que corresponde a cada idioma de la app. */
const INTL_LOCALES: Record<Locale, string> = { es: 'es-ES', en: 'en-US' };

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/**
 * Normaliza un valor de cookie a un Locale soportado. Acepta la forma larga
 * de navegador («es-ES», «en-US») por si la cookie se escribe a mano.
 */
export function parseLocale(value: string | null | undefined): Locale {
  if (!value) return DEFAULT_LOCALE;
  const short = value.trim().toLowerCase().split('-')[0];
  return isLocale(short) ? short : DEFAULT_LOCALE;
}

/** Locale Intl («es-ES» / «en-US») para Intl.NumberFormat y DateTimeFormat. */
export function intlLocale(locale: Locale): string {
  return INTL_LOCALES[locale];
}
