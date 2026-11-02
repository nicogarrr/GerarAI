import type { TranslateFn } from '@/lib/i18n/translate';
import { translateMessage } from '@/lib/i18n/translate';

/**
 * Método de /api/market/themes (market_themes.py, «method»): el backend lo
 * manda en castellano («media simple») y el pie de Temas lo pintaba tal cual
 * también en inglés. El catálogo en castellano guarda la misma palabra; si
 * coincide, se muestra en el idioma activo. Otro texto pasa tal cual.
 */
export function themeMethodText(method: string, t: TranslateFn): string {
  return method === translateMessage('es', 'themes.page.methodSimpleAverage') ? t('themes.page.methodSimpleAverage') : method;
}
