/**
 * Temas (market_themes.py REASONS): el backend manda en castellano por qué
 * está cada ticker en su cesta. En inglés se traduce con la tabla
 * theme-reasons-en.json; en castellano, y con un texto que no se reconoce,
 * pasa el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

import REASONS_EN from './theme-reasons-en.json';

const TABLE: Record<string, string> = REASONS_EN;

export function themeReasonText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  return Object.hasOwn(TABLE, text) ? TABLE[text] : text;
}
