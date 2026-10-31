/** «Qué ha cambiado»: texto de un cambio de métrica (anterior tachado → nuevo), sin inventar nada. */
export interface MetricChange {
    metric: string;
    unidad?: string | null;
    anterior: { valor: number; periodo: string } | null;
    nuevo: { valor: number; periodo: string };
    fuente?: string | null;
}

function amount(value: number, unit?: string | null): string {
    const abs = Math.abs(value);
    const text = abs >= 1e6
        ? value.toLocaleString('es-ES', { notation: 'compact', maximumFractionDigits: 2 })
        : value.toLocaleString('es-ES', { maximumFractionDigits: 2 });
    return unit && unit !== 'pure' ? `${text} ${unit}` : text;
}

export function metricChangeParts(change: MetricChange): { before: string | null; after: string; note: string } {
    const before = change.anterior ? amount(change.anterior.valor, change.unidad) : null;
    const after = amount(change.nuevo.valor, change.unidad);
    const samePeriod = change.anterior?.periodo === change.nuevo.periodo;
    const note = !change.anterior
        ? `dato nuevo (${change.nuevo.periodo})`
        : samePeriod
            ? `${change.nuevo.periodo}, revisado`
            : `${change.anterior.periodo} → ${change.nuevo.periodo}`;
    return { before, after, note };
}
