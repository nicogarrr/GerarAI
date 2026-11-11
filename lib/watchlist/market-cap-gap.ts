/** Motivo de una capitalización N/D en la watchlist (una leyenda por página).
 *  Orden: presupuesto de la fila agotado > lectura del backend fallida
 *  (timeout/5xx: el dato puede existir) > plaza sin cobertura del proveedor >
 *  la fuente respondió sin capitalización. Un fallo de lectura NUNCA se
 *  rotula como ausencia del dato (r5-valor2, 11-nov-2026: AIR.PA/FFH.TO). */
export type MarketCapGapReason = 'timedOut' | 'readFailed' | 'notApplicable' | 'unverifiable';

export const MARKET_CAP_GAP_REASONS: readonly MarketCapGapReason[] = ['timedOut', 'readFailed', 'notApplicable', 'unverifiable'];

export function marketCapGapReason(stock: {
    marketCap: number | null;
    timedOut: boolean;
    metricsNotApplicable: boolean;
    metricsReadFailed?: boolean;
}): MarketCapGapReason | null {
    if (stock.marketCap !== null) return null;
    if (stock.timedOut) return 'timedOut';
    if (stock.metricsReadFailed) return 'readFailed';
    return stock.metricsNotApplicable ? 'notApplicable' : 'unverifiable';
}
