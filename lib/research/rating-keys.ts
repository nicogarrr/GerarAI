import type { TranslationKey } from '@/lib/i18n/t';

/**
 * Ratings persistidos por el backend → claves i18n del memo. La página de
 * tesis y ThesisMemo llevaban este mismo mapa copiado; una sola fuente.
 * El índice de research usa otro catálogo (research.rating.*), no este.
 */
export const RATING_KEYS: Record<string, TranslationKey> = {
  buy: 'research.memo.ratingBuy', accumulate: 'research.memo.ratingAccumulate', overweight: 'research.memo.ratingOverweight',
  hold: 'research.memo.ratingHold', underweight: 'research.memo.ratingUnderweight', trim: 'research.memo.ratingTrim',
  sell: 'research.memo.ratingSell', avoid: 'research.memo.ratingAvoid', watch: 'research.memo.ratingWatch',
  attractive: 'research.memo.ratingAttractive', expensive: 'research.memo.ratingExpensive',
  incomplete_price: 'research.memo.ratingIncompletePrice', blocked: 'research.memo.ratingBlocked', insufficient_data: 'research.memo.insufficientData',
};
