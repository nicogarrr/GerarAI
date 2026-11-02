import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';
import { translateMessage } from '@/lib/i18n/translate';

/**
 * thesis_service._catalysts manda la etiqueta del catalizador de resultados en
 * castellano; el catálogo en castellano guarda la misma frase. En inglés, si
 * coincide, se dice en inglés; otra etiqueta (tesis antiguas o redactadas) pasa tal cual.
 */
export function thesisCatalystLabel(label: string, locale: Locale, t: TranslateFn): string {
  return locale === 'en' && label.trim() === translateMessage('es', 'research.memo.catalystNextEarnings')
    ? t('research.memo.catalystNextEarnings')
    : label;
}
