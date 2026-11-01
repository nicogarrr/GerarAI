import type { DcaRun, DcaSignalItem, DcaSignalState } from '@/lib/dca/types';
// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { intlLocale, type Locale } from '../i18n/locale.ts';
// @ts-expect-error TS5097: idem
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
export type DcaT = (key: TranslationKey, vars?: TranslationVars) => string;

const PERCENT = (locale: Locale) => new Intl.NumberFormat(intlLocale(locale), { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const NUMBER = (locale: Locale) => new Intl.NumberFormat(intlLocale(locale), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const RSI = (locale: Locale) => new Intl.NumberFormat(intlLocale(locale), { maximumFractionDigits: 1 });

/** Etiqueta del estado del mes (forming/confirmed) en el idioma elegido. */
export function dcaStatusLabel(status: string, ti: DcaT = esT): string {
    if (status === 'forming') return ti('watchlist.dca.fmt.statusForming');
    if (status === 'confirmed') return ti('watchlist.dca.fmt.statusConfirmed');
    return status;
}

export const DCA_STATUS_LABEL: Record<string, string> = {
    forming: dcaStatusLabel('forming'),
    confirmed: dcaStatusLabel('confirmed'),
};

/** Opciones del selector de nivel mínimo de aviso (valor del Select). */
export const DCA_MIN_LEVEL_OPTIONS: Array<{ value: string; label: string }> = [
    { value: 'global', label: 'Global' },
    { value: '1', label: '1X' },
    { value: '2', label: '2X' },
    { value: '3', label: '3X' },
    { value: '4', label: '4X' },
    { value: '0', label: esT('watchlist.dca.fmt.levelOff') },
];

export function dcaPercent(value: number | string | null | undefined, locale: Locale = 'es'): string | null {
    return typeof value === 'number' && Number.isFinite(value) ? PERCENT(locale).format(value) : null;
}

export function dcaPrice(value: number | null | undefined, currencyLabel: string | null, locale: Locale = 'es'): string | null {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    const number = NUMBER(locale).format(value);
    return currencyLabel ? `${number} ${currencyLabel}` : number;
}

export function dcaRsi(value: number | string | null | undefined, locale: Locale = 'es'): string | null {
    return typeof value === 'number' && Number.isFinite(value) ? RSI(locale).format(value) : null;
}

/** Métrica que decide el nivel de compra, con su etiqueta. */
export function dcaSignalMetric(state: DcaSignalState, signalMonths: number | null, ti: DcaT = esT, locale: Locale = 'es'): { label: string; value: string } | null {
    const metrics = state.metrics ?? {};
    if (metrics.signal === 'sma_gap') {
        const value = dcaPercent(metrics.sma_gap, locale);
        if (value) return { label: signalMonths ? ti('watchlist.dca.fmt.metricSmaGap', { months: signalMonths }) : ti('watchlist.dca.fmt.metricSmaGapLong'), value };
    }
    const drawdown = dcaPercent(metrics.drawdown, locale);
    return drawdown ? { label: ti('watchlist.dca.fmt.metricDrawdown'), value: drawdown } : null;
}

/** Edad de los datos de la señal («hoy», «hace 1 día», «hace 9 días»). */
export function dcaDataAge(days: number | null | undefined, ti: DcaT = esT): string | null {
    if (typeof days !== 'number' || !Number.isFinite(days) || days < 0) return null;
    const whole = Math.floor(days);
    if (whole === 0) return ti('watchlist.dca.fmt.ageToday');
    return whole === 1 ? ti('watchlist.dca.fmt.ageOne') : ti('watchlist.dca.fmt.ageOther', { count: whole });
}

/** Texto corto de datos viejos junto al badge («desactualizado · hace 9 días»). */
export function dcaStaleText(age: string | null, ti: DcaT = esT): string {
    return age ? ti('watchlist.dca.fmt.staleAge', { age }) : ti('watchlist.dca.fmt.stale');
}

export function dcaSkipReason(reason: string | null | undefined, ti: DcaT = esT): string {
    if (!reason) return ti('watchlist.dca.fmt.skipDefault');
    if (reason === 'datos_desactualizados') return ti('watchlist.dca.fmt.skipStale');
    if (reason === 'sin_datos') return ti('watchlist.dca.fmt.skipNoData');
    if (reason === 'historia_insuficiente') return ti('watchlist.dca.fmt.skipShortHistory');
    return reason;
}

/** Texto del badge de un ticker sin nivel: nunca ejecutado, fallo del job u omitido. */
export function dcaMissingBadge(item: DcaSignalItem | undefined, ti: DcaT = esT): { text: string; title: string; tone: 'neutral' | 'error' | 'warn' } {
    const status = item?.evaluation_status ?? 'never_run';
    if (status === 'job_failed') {
        return {
            text: ti('watchlist.dca.fmt.failedText'),
            title: ti('watchlist.dca.fmt.failedTitle', { reason: item?.evaluation_reason ? `: ${item.evaluation_reason.replace(/\.+$/, '')}` : '' }),
            tone: 'error',
        };
    }
    if (status === 'skipped') {
        return {
            text: ti('watchlist.dca.fmt.skippedText'),
            title: ti('watchlist.dca.fmt.skippedTitle', { reason: dcaSkipReason(item?.evaluation_reason, ti) }),
            tone: 'warn',
        };
    }
    if (status === 'running') {
        return { text: ti('watchlist.dca.fmt.runningText'), title: ti('watchlist.dca.fmt.runningTitle'), tone: 'neutral' };
    }
    if (status === 'pending') {
        return { text: ti('watchlist.dca.fmt.pendingText'), title: ti('watchlist.dca.fmt.pendingTitle'), tone: 'neutral' };
    }
    if (status === 'unknown') {
        return { text: ti('watchlist.dca.fmt.unknownText'), title: ti('watchlist.dca.fmt.unknownTitle'), tone: 'warn' };
    }
    return { text: ti('watchlist.dca.fmt.neverText'), title: ti('watchlist.dca.fmt.neverTitle'), tone: 'neutral' };
}

const WHEN = (locale: Locale) => new Intl.DateTimeFormat(intlLocale(locale), {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid',
});

/** Resumen de una línea de la última ejecución, o null si nunca hubo. */
export function dcaRunSummary(run: DcaRun | null | undefined, ti: DcaT = esT, locale: Locale = 'es'): { text: string; tone: 'neutral' | 'ok' | 'error' | 'warn' } {
    if (!run) return { text: ti('watchlist.dca.fmt.runNone'), tone: 'neutral' };
    const when = WHEN(locale).format(new Date(run.finished_at ?? run.started_at));
    const origin = run.trigger === 'manual' ? ti('watchlist.dca.fmt.originManual') : ti('watchlist.dca.fmt.originAuto');
    if (run.status === 'running') return { text: ti('watchlist.dca.fmt.runRunning', { origin, when }), tone: 'neutral' };
    if (run.status === 'interrupted') {
        return { text: ti('watchlist.dca.fmt.runInterrupted', { origin, when }), tone: 'error' };
    }
    if (run.status === 'error') {
        return { text: ti('watchlist.dca.fmt.runError', { origin, when, error: run.error ? `: ${run.error}` : '' }), tone: 'error' };
    }
    const parts = [ti('watchlist.dca.fmt.runEvaluated', { evaluated: run.evaluated, tracked: run.tracked })];
    if (run.skipped > 0) parts.push(run.skipped === 1 ? ti('watchlist.dca.fmt.runSkippedOne', { count: run.skipped }) : ti('watchlist.dca.fmt.runSkippedOther', { count: run.skipped }));
    if (run.errors > 0) parts.push(ti('watchlist.dca.fmt.runErrors', { count: run.errors }));
    return { text: ti('watchlist.dca.fmt.runDone', { origin, when, parts: parts.join(', ') }), tone: run.errors > 0 || run.evaluated < run.tracked ? 'warn' : 'ok' };
}
