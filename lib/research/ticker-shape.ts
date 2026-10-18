/**
 * Forma plausible de un ticker: hasta 6 caracteres alfanuméricos y, opcional,
 * un sufijo de mercado o clase tras punto o guion (SAN.MC, BRK.B, BTC-USD) o
 * un índice con ^ o un par/futuro de Yahoo con =X / =F (EURUSD=X, GC=F). Una ruta como /research/settings no lo cumple (8 letras) y
 * debe dar 404 normal en vez de abrir una ficha de «SETTINGS».
 */
const TICKER_SHAPE = /^\^?[A-Z0-9]{1,6}([.-][A-Z0-9]{1,4})?(=[A-Z])?$/;

export function looksLikeTicker(raw: string): boolean {
  let value = raw;
  try {
    value = decodeURIComponent(raw);
  } catch {
    return false;
  }
  return TICKER_SHAPE.test(value.trim().toUpperCase());
}
