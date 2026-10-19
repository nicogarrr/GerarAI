/**
 * G/P en divisa nativa cuando el signo de la G/P en divisa base la contradice
 * (ej. la acción sube en USD pero la G/P en EUR es negativa). Solo usa campos
 * reales del backend (unrealized_pnl_native y cost_basis_native); si falta
 * alguno o las divisas coinciden, devuelve null y no se muestra nada.
 */
export type NativePnl = { amount: number; percent: number | null; currency: string };

export function nativePnlIfContradicts(input: {
  gain: number;
  gainKnown: boolean;
  nativeGain: number | null | undefined;
  nativeCost: number | null | undefined;
  nativeCurrency: string;
  baseCurrency: string;
}): NativePnl | null {
  const { gain, gainKnown, nativeGain, nativeCost, nativeCurrency, baseCurrency } = input;
  if (!gainKnown || nativeGain == null || !Number.isFinite(nativeGain)) return null;
  if (!nativeCurrency || !baseCurrency || nativeCurrency === baseCurrency) return null;
  if (gain === 0 || nativeGain === 0) return null;
  if (gain > 0 === nativeGain > 0) return null;
  const percent = nativeCost != null && Number.isFinite(nativeCost) && nativeCost > 0 ? (nativeGain / nativeCost) * 100 : null;
  return { amount: nativeGain, percent, currency: nativeCurrency };
}
