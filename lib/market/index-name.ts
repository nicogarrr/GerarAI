/**
 * Nombres de los índices de /api/market/indices (market.py, _INDEXES): el
 * backend nombra el oro y la plata en castellano. En inglés se muestran en
 * inglés; los demás nombres (S&P 500, Nasdaq, Bitcoin) ya valen en los dos
 * idiomas. Un nombre que no es el esperado pasa tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const NAMES_EN: Record<string, { es: string; en: string }> = {
  'GC=F': { es: 'Oro', en: 'Gold' },
  'SI=F': { es: 'Plata', en: 'Silver' },
};

export function marketIndexName(index: { symbol: string; name: string }, locale: Locale): string {
  const known = NAMES_EN[index.symbol];
  return locale === 'en' && known && known.es === index.name ? known.en : index.name;
}
