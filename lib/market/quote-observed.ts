/** Quote time is not a confirmed closing date. Do not relabel a live candle. */
export function quoteObserved(timestamp?: number | null, kind?: 'daily_candle_open' | 'quote', locale: 'es' | 'en' = 'es'): string {
  if (locale === 'en') return quoteObservedEn(timestamp, kind);
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return 'Fecha N/D: proveedor sin fecha';
  const date = new Date(timestamp * 1000);
  if (!Number.isFinite(date.getTime())) return 'Fecha N/D: proveedor sin fecha';
  const label = kind === 'daily_candle_open' ? 'Última vela diaria (hora de apertura)' : 'Cotización';
  return `${label} ${new Intl.DateTimeFormat('es-ES', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  }).format(date)} UTC`;
}

/** Misma lectura en inglés (Ajustes → Idioma). */
function quoteObservedEn(timestamp?: number | null, kind?: 'daily_candle_open' | 'quote'): string {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return 'Date N/A: provider has no date';
  const date = new Date(timestamp * 1000);
  if (!Number.isFinite(date.getTime())) return 'Date N/A: provider has no date';
  const label = kind === 'daily_candle_open' ? 'Last daily candle (open time)' : 'Quote';
  return `${label} ${new Intl.DateTimeFormat('en-US', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  }).format(date)} UTC`;
}
