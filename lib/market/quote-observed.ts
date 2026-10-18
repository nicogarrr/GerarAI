/** Quote time is not a confirmed closing date. Do not relabel a live candle. */
export function quoteObserved(timestamp?: number | null, kind?: 'daily_candle_open' | 'quote'): string {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return 'Fecha N/D: proveedor sin fecha';
  const date = new Date(timestamp * 1000);
  if (!Number.isFinite(date.getTime())) return 'Fecha N/D: proveedor sin fecha';
  const label = kind === 'daily_candle_open' ? 'Última vela diaria (hora de apertura)' : 'Cotización';
  return `${label} ${new Intl.DateTimeFormat('es-ES', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  }).format(date)} UTC`;
}
