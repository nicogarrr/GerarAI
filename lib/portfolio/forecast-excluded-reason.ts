/**
 * Motivos por los que /api/portfolio/forecast deja fuera una posición.
 * El backend los manda en castellano junto a un `reason_code`; en inglés se
 * traducen por código (y por variante cuando un mismo código tiene varias
 * frases). En castellano, y con un código o texto que no se reconoce, el
 * texto del backend pasa tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

const HOLD_SPLIT_ES = /^split (\S+) de (\d{4}-\d{2}-\d{2}) aplicado sin precio post-split verificado: valoracion no disponible$/;

/** Motivo guardado de una valoración en suspenso (corporate_actions_service), en el idioma de la interfaz. */
export function valuationHoldReason(reason: string, locale: Locale): string {
  if (locale !== 'en') return reason;
  const split = HOLD_SPLIT_ES.exec(reason.trim());
  return split ? `${split[1]} split of ${split[2]} applied without a verified post-split price: valuation not available` : reason;
}

export function forecastExcludedReason(
  item: { reason_code?: string | null; reason: string },
  locale: Locale,
  t: TranslateFn,
): string {
  const text = item.reason ?? '';
  if (locale !== 'en') return text;
  switch (item.reason_code) {
    case 'no_published_thesis':
      return t(text.includes('borrador') ? 'portfolio.forecast.excludedReason.noThesisDraft' : 'portfolio.forecast.excludedReason.noThesis');
    case 'valuation_basis_unverified':
      if (text.startsWith('ADR')) return t('portfolio.forecast.excludedReason.adrWithoutListedValues');
      if (text.startsWith('Moneda')) return t('portfolio.forecast.excludedReason.currencyMismatch');
      return t('portfolio.forecast.excludedReason.basisUnverified');
    case 'no_computable_intrinsic':
      return t('portfolio.forecast.excludedReason.noComputableIntrinsic');
    case 'no_base_value':
      return t('portfolio.forecast.excludedReason.noBaseValue');
    case 'valuation_hold': {
      const held = /^Valoración pendiente: ([\s\S]*?)\.?$/.exec(text);
      return held ? t('portfolio.forecast.excludedReason.valuationHold', { reason: valuationHoldReason(held[1], locale) }) : text;
    }
    default:
      return text;
  }
}
