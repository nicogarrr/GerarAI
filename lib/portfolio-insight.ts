/**
 * Decision de la frase "tu cartera en una linea" de /inicio (F38).
 *
 * La frase se deriva SOLO del resumen de cartera. Antes se calculaba en el
 * efecto despues del waterfall de oportunidades (DCF de 6 simbolos), asi que
 * durante segundos la tarjeta mostraba "Todavia no tienes posiciones" con la
 * cartera ya cargada al lado. Al ser una funcion pura del resumen, el texto
 * no puede desacoplarse del dato.
 *
 * Sin base de coste no hay frase de movimiento (F17): un "0,00%" seria
 * inventado. Vacio no es cero: sin posiciones la tarjeta pide anadir la
 * primera inversion, no pinta una rentabilidad.
 */
export interface PortfolioInsightHolding {
    readonly symbol: string;
    readonly cost: number;
    readonly gain: number;
    readonly gainPercent: number;
    readonly fxMissing?: boolean;
    /** Coste IBKR pendiente de revisión: no es base de coste fiable. */
    readonly costReviewMessage?: string | null;
}

export interface PortfolioInsightSummary {
    readonly holdings: readonly PortfolioInsightHolding[];
}

export type PortfolioInsight =
    | { readonly kind: 'empty' }
    | { readonly kind: 'no-cost-basis' }
    | {
          readonly kind: 'movement';
          readonly direction: 'up' | 'down';
          readonly totalPercent: number;
          readonly topSymbol: string;
          readonly topGainPercent: number;
          /** true si alguna posicion quedo fuera del calculo (sin base de
           *  coste o sin FX): el porcentaje cubre solo una parte de la
           *  cartera y la frase debe decirlo, no presentarlo como global. */
          readonly partial: boolean;
      };

export function buildPortfolioInsight(summary: PortfolioInsightSummary | null | undefined): PortfolioInsight {
    if (!summary || summary.holdings.length === 0) return { kind: 'empty' };
    const conCoste = summary.holdings.filter((h) => h.cost > 0 && !h.fxMissing && !h.costReviewMessage);
    if (conCoste.length === 0) return { kind: 'no-cost-basis' };
    const topMover = conCoste.reduce((a, b) => (Math.abs(b.gainPercent) > Math.abs(a.gainPercent) ? b : a));
    const costeTotal = conCoste.reduce((sum, h) => sum + h.cost, 0);
    const gananciaTotal = conCoste.reduce((sum, h) => sum + h.gain, 0);
    const totalPercent = costeTotal > 0 ? (gananciaTotal / costeTotal) * 100 : 0;
    return {
        kind: 'movement',
        direction: totalPercent >= 0 ? 'up' : 'down',
        totalPercent,
        topSymbol: topMover.symbol,
        topGainPercent: topMover.gainPercent,
        partial: conCoste.length < summary.holdings.length,
    };
}

/**
 * Hay base de coste conocida en al menos una posicion (coste > 0 y FX resuelto).
 * Sin ella, coste total, ganancia y rendimiento son N/D: un "0,00 EUR" o un
 * "+0,00 %" se leeria como dato real y es solo ausencia de base (F2).
 */
export function hasCostBasis(summary: PortfolioInsightSummary | null | undefined): boolean {
    return buildPortfolioInsight(summary).kind === 'movement';
}
