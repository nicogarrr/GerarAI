// Qué mostrar de una posición en Inicio. El valor convertido y el coste son
// disponibilidades distintas: sin base de coste no hay rentabilidad (N/D), pero
// el valor sigue siendo válido si su conversión existe.
export type HoldingDisplayInput = {
    cost: number;
    value: number;
    valueMissing: boolean;
    fxMissing: boolean;
    quoteMissing?: boolean;
};

export type HoldingDisplayMode = 'gain' | 'value' | 'na';

export function holdingDisplayMode(h: HoldingDisplayInput): HoldingDisplayMode {
    if (h.cost > 0 && !h.fxMissing && !h.quoteMissing) return 'gain';
    if (!h.valueMissing && h.value > 0) return 'value';
    return 'na';
}

/** Texto visible de una valoración en suspensión: motivo y fecha, nunca un 0 como cotización. */
export function valuationHoldLabel(hold: { reason: string; effectiveDate: string | null }): string {
    const date = hold.effectiveDate ? hold.effectiveDate.split('-').reverse().join('/') : null;
    return date ? `Valoración pendiente: split del ${date} sin precio post-split verificado` : 'Valoración pendiente: sin precio post-split verificado';
}
