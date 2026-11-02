/**
 * Posiciones cortas públicas (short_positions_service.py y cnmv_shorts.py):
 * el backend manda en castellano el motivo del estado y la nota de la
 * fuente. En inglés se traducen; en castellano, y con un texto que no se
 * reconoce, pasa el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const SHORTS_EN: Record<string, string> = {
  'No hay mapeo revisado para esta bolsa o empresa.': 'There is no reviewed mapping for this exchange or company.',
  'La fuente no devolvió datos verificables; el dato anterior conserva su fecha.':
    'The source returned no verifiable data; the previous figure keeps its date.',
  'Consulta o fecha de negociación fuera del límite de 4 días.': 'Lookup or trade date outside the 4-day limit.',
  'No hay consulta almacenada. Usa Actualizar para consultar la fuente pública.': 'No stored lookup. Use Refresh to query the public source.',
  'Volumen corto diario fuera de bolsa, no posiciones abiertas ni porcentaje total del mercado. No implica sentimiento bajista por sí solo.':
    'Daily off-exchange short volume, not open positions or a share of the whole market. It does not imply bearish sentiment on its own.',
  'Solo posiciones públicas >=0,5%. La suma no es el total de cortos del mercado; fechas distintas por titular.':
    'Only public positions >=0.5%. The sum is not the market’s total short interest; dates differ by holder.',
};

export function shortsText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  return Object.hasOwn(SHORTS_EN, text) ? SHORTS_EN[text] : text;
}
