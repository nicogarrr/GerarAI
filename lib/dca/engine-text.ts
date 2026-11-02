import type { TranslationKey } from '@/lib/i18n/t';
import type { TranslateFn } from '@/lib/i18n/translate';
import { translateMessage } from '@/lib/i18n/translate';

/**
 * Etiquetas del motor DCA que el backend manda solo en castellano: nivel
 * («RECORTE LIGERO»), zona («Zona de compra extrema»; dca_signal_engine.ZONES),
 * grupo de aciertos («Todos 2X–4X»; HIT_RATE_GROUPS) y planes del backtest
 * («DCA plano»; dca_backtest). El catálogo en castellano guarda la misma frase;
 * si coincide, se muestra la clave en el idioma activo. «4X DCA» y cualquier
 * texto distinto pasan tal cual.
 */
const ENGINE_KEYS: readonly TranslationKey[] = [
  'watchlist.dca.engine.lightTrim',
  'watchlist.dca.engine.strongTrim',
  'watchlist.dca.engine.all2x4x',
  'watchlist.dca.engine.zoneExtreme',
  'watchlist.dca.engine.zoneStrong',
  'watchlist.dca.engine.zoneBuy',
  'watchlist.dca.engine.zoneNormal',
  'watchlist.dca.engine.zoneLightTrim',
  'watchlist.dca.engine.zoneStrongTrim',
  'watchlist.dca.engine.planPlain',
  'watchlist.dca.engine.planLevels',
  'watchlist.dca.engine.planFixed',
];

export function dcaEngineText(text: string, t: TranslateFn): string {
  const key = ENGINE_KEYS.find((k) => translateMessage('es', k) === text);
  return key ? t(key) : text;
}
