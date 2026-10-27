import type { DcaSignalState } from '@/lib/dca/types';

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
