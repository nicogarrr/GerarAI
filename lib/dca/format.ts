import type { DcaRun, DcaSignalItem, DcaSignalState } from '@/lib/dca/types';

const PERCENT = new Intl.NumberFormat('es-ES', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const NUMBER = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const RSI = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });

export const DCA_STATUS_LABEL: Record<string, string> = {
    forming: 'en formación (provisional)',
    confirmed: 'confirmado',
};

/** Opciones del selector de nivel mínimo de aviso (valor del Select). */
export const DCA_MIN_LEVEL_OPTIONS: Array<{ value: string; label: string }> = [
    { value: 'global', label: 'Global' },
    { value: '1', label: '1X' },
    { value: '2', label: '2X' },
    { value: '3', label: '3X' },
    { value: '4', label: '4X' },
    { value: '0', label: 'Desactivado' },
];

export function dcaPercent(value: number | string | null | undefined): string | null {
    return typeof value === 'number' && Number.isFinite(value) ? PERCENT.format(value) : null;
}

export function dcaPrice(value: number | null | undefined, currencyLabel: string | null): string | null {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    const number = NUMBER.format(value);
    return currencyLabel ? `${number} ${currencyLabel}` : number;
}

export function dcaRsi(value: number | string | null | undefined): string | null {
    return typeof value === 'number' && Number.isFinite(value) ? RSI.format(value) : null;
}

/** Métrica que decide el nivel de compra, con su etiqueta. */
export function dcaSignalMetric(state: DcaSignalState, signalMonths: number | null): { label: string; value: string } | null {
    const metrics = state.metrics ?? {};
    if (metrics.signal === 'sma_gap') {
        const value = dcaPercent(metrics.sma_gap);
        if (value) return { label: signalMonths ? `Distancia bajo media ${signalMonths}m` : 'Distancia bajo media larga', value };
    }
    const drawdown = dcaPercent(metrics.drawdown);
    return drawdown ? { label: 'Caída desde máximo 36m', value: drawdown } : null;
}

/** Edad de los datos de la señal («hoy», «hace 1 día», «hace 9 días»). */
export function dcaDataAge(days: number | null | undefined): string | null {
    if (typeof days !== 'number' || !Number.isFinite(days) || days < 0) return null;
    const whole = Math.floor(days);
    if (whole === 0) return 'hoy';
    return whole === 1 ? 'hace 1 día' : `hace ${whole} días`;
}

const SKIP_REASON: Record<string, string> = {
    datos_desactualizados: 'datos de precio demasiado viejos',
    sin_datos: 'sin datos de precio',
    historia_insuficiente: 'historia insuficiente',
};

export function dcaSkipReason(reason: string | null | undefined): string {
    if (!reason) return 'omitido';
    return SKIP_REASON[reason] ?? reason;
}

/** Texto del badge de un ticker sin nivel: nunca ejecutado, fallo del job u omitido. */
export function dcaMissingBadge(item: DcaSignalItem | undefined): { text: string; title: string; tone: 'neutral' | 'error' | 'warn' } {
    const status = item?.evaluation_status ?? 'never_run';
    if (status === 'job_failed') {
        return {
            text: 'Evaluación fallida',
            title: `La última evaluación falló para este ticker${item?.evaluation_reason ? `: ${item.evaluation_reason.replace(/\.+$/, '')}` : ''}.`,
            tone: 'error',
        };
    }
    if (status === 'skipped') {
        return {
            text: 'Omitido',
            title: `La evaluación lo omitió: ${dcaSkipReason(item?.evaluation_reason)}.`,
            tone: 'warn',
        };
    }
    if (status === 'running') {
        return { text: 'En curso', title: 'Hay una evaluación en curso; el nivel aparecerá al terminar.', tone: 'neutral' };
    }
    if (status === 'pending') {
        return {
            text: 'Pendiente',
            title: 'Hay una ejecución registrada, pero este ticker no figuraba en ella (por ejemplo, añadido después). Se evaluará en la siguiente.',
            tone: 'neutral',
        };
    }
    if (status === 'unknown') {
        return {
            text: 'Estado desconocido',
            title: 'El detalle guardado de la última ejecución está truncado y no permite saber qué pasó con este ticker.',
            tone: 'warn',
        };
    }
    return {
        text: 'Sin evaluar',
        title: 'No consta ninguna evaluación ejecutada. Se evalúa tras el cierre (L-V) o con «Evaluar ahora».',
        tone: 'neutral',
    };
}

const WHEN = new Intl.DateTimeFormat('es-ES', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid',
});

/** Resumen de una línea de la última ejecución, o null si nunca hubo. */
export function dcaRunSummary(run: DcaRun | null | undefined): { text: string; tone: 'neutral' | 'ok' | 'error' | 'warn' } {
    if (!run) return { text: 'Última ejecución: ninguna registrada todavía', tone: 'neutral' };
    const when = WHEN.format(new Date(run.finished_at ?? run.started_at));
    const origin = run.trigger === 'manual' ? 'manual' : 'automática';
    if (run.status === 'running') return { text: `Evaluación ${origin} en curso desde ${when}`, tone: 'neutral' };
    if (run.status === 'interrupted') {
        return { text: `Última ejecución (${origin}, ${when}) interrumpida: no llegó a terminar`, tone: 'error' };
    }
    if (run.status === 'error') {
        return { text: `Última ejecución (${origin}, ${when}) falló${run.error ? `: ${run.error}` : ''}`, tone: 'error' };
    }
    const parts = [`${run.evaluated} de ${run.tracked} evaluados`];
    if (run.skipped > 0) parts.push(`${run.skipped} ${run.skipped === 1 ? 'omitido' : 'omitidos'}`);
    if (run.errors > 0) parts.push(`${run.errors} con error`);
    return { text: `Última ejecución (${origin}, ${when}): ${parts.join(', ')}`, tone: run.errors > 0 || run.evaluated < run.tracked ? 'warn' : 'ok' };
}
