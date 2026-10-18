/** Quote time is not a confirmed closing date. Do not relabel a live candle. */
export function quoteObserved(timestamp?: number | null): string {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) return 'Fecha N/D: proveedor sin fecha';
  const date = new Date(timestamp * 1000);
  if (!Number.isFinite(date.getTime())) return 'Fecha N/D: proveedor sin fecha';
  return `Cotización ${new Intl.DateTimeFormat('es-ES', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  }).format(date)} UTC`;
}
