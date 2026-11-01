/** «Qué ha cambiado»: texto de un cambio de métrica (anterior tachado → nuevo), sin inventar nada. */
export interface MetricChange {
    metric: string;
    unidad?: string | null;
    anterior: { valor: number; periodo: string } | null;
    nuevo: { valor: number; periodo: string };
    fuente?: string | null;
}

function amount(value: number, unit?: string | null, locale: 'es' | 'en' = 'es'): string {
    const abs = Math.abs(value);
    const tag = locale === 'en' ? 'en-US' : 'es-ES';
    const text = abs >= 1e6
        ? value.toLocaleString(tag, { notation: 'compact', maximumFractionDigits: 2 })
        : value.toLocaleString(tag, { maximumFractionDigits: 2 });
    return unit && unit !== 'pure' ? `${text} ${unit}` : text;
}

export function metricChangeParts(change: MetricChange, locale: 'es' | 'en' = 'es'): { before: string | null; after: string; note: string } {
    const before = change.anterior ? amount(change.anterior.valor, change.unidad, locale) : null;
    const after = amount(change.nuevo.valor, change.unidad, locale);
    const samePeriod = change.anterior?.periodo === change.nuevo.periodo;
    const note = !change.anterior
        ? (locale === 'en' ? `new figure (${change.nuevo.periodo})` : `dato nuevo (${change.nuevo.periodo})`)
        : samePeriod
            ? (locale === 'en' ? `${change.nuevo.periodo}, revised` : `${change.nuevo.periodo}, revisado`)
            : `${change.anterior.periodo} → ${change.nuevo.periodo}`;
    return { before, after, note };
}
