/**
 * «Precio y eventos» del gráfico de la ficha: cálculos puros sobre las velas que
 * el gráfico ya tiene (sin pedir precios nuevos) y los eventos guardados.
 * Idea de Tracking Alpha (Jera Value): precio, indicador, volumen y eventos juntos.
 */

// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { intlLocale, type Locale } from '../i18n/locale.ts';
// @ts-expect-error TS5097: idem
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
export type EventsT = (key: TranslationKey, vars?: TranslationVars) => string;

export type PriceEventKind = 'results' | 'ex_dividend' | 'filing' | 'insider' | 'news' | 'movement';

export interface PriceEvent {
    id: string;
    date: string;
    kind: PriceEventKind;
    title: string;
    detail?: string | null;
    source: string;
    source_url?: string | null;
}

export interface EventBar {
    date: string;
    close: number;
    high?: number | null;
    volume?: number | null;
}

export const EVENT_KINDS: Record<PriceEventKind, { label: string; short: string; color: string }> = {
    results: { label: 'Resultados', short: 'R', color: '#60a5fa' },
    ex_dividend: { label: 'Ex-dividendo', short: 'D', color: '#34d399' },
    filing: { label: 'Filings', short: 'F', color: '#a78bfa' },
    insider: { label: 'Insiders', short: 'I', color: '#f59e0b' },
    news: { label: 'Noticias', short: 'N', color: '#f472b6' },
    movement: { label: 'Movimiento', short: 'M', color: '#f87171' },
};

/** Clave de traducción de cada tipo de evento (la etiqueta de EVENT_KINDS es el español de referencia). */
export const EVENT_KIND_KEYS: Record<PriceEventKind, TranslationKey> = {
    results: 'research.chart.kindResults',
    ex_dividend: 'research.chart.kindExDividend',
    filing: 'research.chart.kindFiling',
    insider: 'research.chart.kindInsider',
    news: 'research.chart.kindNews',
    movement: 'research.chart.kindMovement',
};

export const EVENT_KIND_ORDER: PriceEventKind[] = ['results', 'ex_dividend', 'filing', 'insider', 'news', 'movement'];

export type IndicatorKind = 'target' | 'drawdown' | 'pnl';

export const INDICATOR_LABELS: Record<IndicatorKind, string> = {
    target: 'Distancia al objetivo',
    drawdown: 'Caída desde máximo 52 sem.',
    pnl: 'Plusvalía latente',
};

export const INDICATOR_KEYS: Record<IndicatorKind, TranslationKey> = {
    target: 'research.chart.indicatorTarget',
    drawdown: 'research.chart.indicatorDrawdown',
    pnl: 'research.chart.indicatorPnl',
};

export const VOLUME_SPIKE_RATIO = 2.5;
export const VOLUME_WINDOW = 60;

function finite(value: number | null | undefined): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

/** true si el volumen de la sesión es ≥ 2,5 veces la media de las 60 sesiones anteriores. */
export function volumeSpikeFlags(bars: EventBar[], window = VOLUME_WINDOW, ratio = VOLUME_SPIKE_RATIO): boolean[] {
    return bars.map((bar, index) => {
        if (!finite(bar.volume) || bar.volume <= 0) return false;
        const previous = bars.slice(Math.max(0, index - window), index).map((b) => b.volume).filter((v): v is number => finite(v) && v > 0);
        if (previous.length < Math.min(20, window)) return false;
        const average = previous.reduce((sum, v) => sum + v, 0) / previous.length;
        return average > 0 && bar.volume >= ratio * average;
    });
}

/** Indicadores disponibles: sin objetivo de analistas o sin posición no se ofrecen. */
export function availableIndicators(opts: { target?: number | null; averageCost?: number | null }): IndicatorKind[] {
    const out: IndicatorKind[] = [];
    if (finite(opts.target) && opts.target > 0) out.push('target');
    out.push('drawdown');
    if (finite(opts.averageCost) && opts.averageCost > 0) out.push('pnl');
    return out;
}

const round2 = (value: number) => Math.round(value * 100) / 100;

/** Serie del panel del indicador, en % (null si no se puede calcular sin inventar datos). */
export function indicatorSeries(
    bars: EventBar[],
    kind: IndicatorKind,
    opts: { target?: number | null; averageCost?: number | null },
): Array<{ date: string; value: number }> {
    if (kind === 'target') {
        if (!finite(opts.target) || opts.target <= 0) return [];
        const target = opts.target;
        return bars.filter((b) => finite(b.close) && b.close > 0).map((b) => ({ date: b.date, value: round2((target / b.close - 1) * 100) }));
    }
    if (kind === 'pnl') {
        if (!finite(opts.averageCost) || opts.averageCost <= 0) return [];
        const cost = opts.averageCost;
        return bars.filter((b) => finite(b.close) && b.close > 0).map((b) => ({ date: b.date, value: round2((b.close / cost - 1) * 100) }));
    }
    const out: Array<{ date: string; value: number }> = [];
    bars.forEach((bar, index) => {
        if (!finite(bar.close) || bar.close <= 0) return;
        const start = new Date(`${bar.date.slice(0, 10)}T00:00:00Z`).getTime() - 365 * 86_400_000;
        let peak = 0;
        for (let i = index; i >= 0; i -= 1) {
            const b = bars[i];
            if (new Date(`${b.date.slice(0, 10)}T00:00:00Z`).getTime() <= start) break;
            const high = finite(b.high) && b.high > 0 ? b.high : b.close;
            if (high > peak) peak = high;
        }
        if (peak > 0) out.push({ date: bar.date, value: round2((bar.close / peak - 1) * 100) });
    });
    return out;
}

/** Eventos dentro del tramo visible (ambos extremos incluidos), los más recientes primero. */
export function eventsInRange<T extends { date: string; id: string }>(events: T[], from: string | undefined, to: string | undefined): T[] {
    if (!from || !to) return [];
    const lo = from.slice(0, 10);
    const hi = to.slice(0, 10);
    return events
        .filter((e) => e.date >= lo && e.date <= hi)
        .sort((a, b) => (a.date === b.date ? b.id.localeCompare(a.id) : b.date.localeCompare(a.date)));
}

export interface DayMarker {
    date: string;
    kinds: PriceEventKind[];
    count: number;
    text: string;
    color: string;
}

/** Una marca por día: los días con varios eventos se juntan y muestran cuántos hay. */
export function markersByDay(events: PriceEvent[], hidden: ReadonlySet<PriceEventKind>): DayMarker[] {
    const byDay = new Map<string, PriceEvent[]>();
    for (const event of events) {
        if (hidden.has(event.kind)) continue;
        const list = byDay.get(event.date) ?? [];
        list.push(event);
        byDay.set(event.date, list);
    }
    return [...byDay.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, list]) => {
            const kinds = EVENT_KIND_ORDER.filter((kind) => list.some((e) => e.kind === kind));
            const first = EVENT_KINDS[kinds[0]];
            return {
                date,
                kinds,
                count: list.length,
                text: list.length > 1 ? `${list.length}` : first.short,
                color: kinds.length > 1 ? '#e5e7eb' : first.color,
            };
        });
}

/** Velas desde la primera compra (incluida). */
export function barsSince<T extends { date: string }>(bars: T[], firstDate: string | null | undefined): T[] {
    if (!firstDate) return bars;
    const day = firstDate.slice(0, 10);
    return bars.filter((bar) => bar.date.slice(0, 10) >= day);
}

export const MOVE_SIGMA = 2.5;
export const MOVE_MIN_PCT = 0.04;

export interface Movement {
    date: string;
    change: number;
    volumeRatio: number | null;
    byPrice: boolean;
    byVolume: boolean;
}

/**
 * «Movimiento»: |variación diaria| ≥ máx(2,5 σ de las 60 sesiones previas, 4 %) o volumen ≥ 2,5× su media.
 * Sin 20 sesiones previas no se juzga (no hay σ fiable).
 */
export function detectMovements(bars: EventBar[], window = VOLUME_WINDOW): Movement[] {
    const returns = bars.map((bar, i) => (i > 0 && finite(bars[i - 1].close) && bars[i - 1].close > 0 && finite(bar.close) ? bar.close / bars[i - 1].close - 1 : null));
    const out: Movement[] = [];
    for (let i = 1; i < bars.length; i += 1) {
        const change = returns[i];
        if (change == null) continue;
        const previous = returns.slice(Math.max(1, i - window), i).filter((r): r is number => r != null);
        if (previous.length < 20) continue;
        const mean = previous.reduce((s, r) => s + r, 0) / previous.length;
        const sigma = Math.sqrt(previous.reduce((s, r) => s + (r - mean) ** 2, 0) / (previous.length - 1));
        const volumes = bars.slice(Math.max(0, i - window), i).map((b) => b.volume).filter((v): v is number => finite(v) && v > 0);
        const avgVolume = volumes.length >= 20 ? volumes.reduce((s, v) => s + v, 0) / volumes.length : null;
        const volume = bars[i].volume;
        const volumeRatio = avgVolume && finite(volume) ? volume / avgVolume : null;
        const byPrice = Math.abs(change) >= Math.max(MOVE_SIGMA * sigma, MOVE_MIN_PCT);
        const byVolume = volumeRatio != null && volumeRatio >= VOLUME_SPIKE_RATIO;
        if (byPrice || byVolume) out.push({ date: bars[i].date.slice(0, 10), change, volumeRatio, byPrice, byVolume });
    }
    return out;
}

const pctText = (value: number, locale: Locale) => `${value > 0 ? '+' : ''}${(value * 100).toLocaleString(intlLocale(locale), { maximumFractionDigits: 1, minimumFractionDigits: 1 })}${locale === 'es' ? ' %' : '%'}`;

function shiftDay(day: string, delta: number): string {
    return new Date(Date.parse(`${day}T00:00:00Z`) + delta * 86_400_000).toISOString().slice(0, 10);
}

/**
 * «¿Por qué se movió?»: cada movimiento como evento, con lo que pasó ese día (±1) o «Sin noticias ese día».
 * Nunca afirma la causa: «puede explicarlo».
 */
export function movementEvents(movements: Movement[], events: PriceEvent[], ti: EventsT = esT, locale: Locale = 'es'): PriceEvent[] {
    return movements.map((move) => {
        const near = events.filter((e) => e.kind !== 'movement' && e.date >= shiftDay(move.date, -1) && e.date <= shiftDay(move.date, 1));
        const parts: string[] = [];
        if (move.byPrice) parts.push(ti('research.chart.moveDay', { pct: pctText(move.change, locale) }));
        if (move.byVolume && move.volumeRatio != null) parts.push(ti('research.chart.moveVolume', { ratio: move.volumeRatio.toLocaleString(intlLocale(locale), { maximumFractionDigits: 1 }) }));
        const detail = near.length
            ? `${ti('research.chart.moveMaybe')}\n${near.map((e) => `· ${e.date} ${ti(EVENT_KIND_KEYS[e.kind])}: ${e.title} (${e.source})`).join('\n')}`
            : ti('research.chart.moveNoNews');
        return {
            id: `movement-${move.date}`,
            date: move.date,
            kind: 'movement' as const,
            title: ti('research.chart.moveTitle', { parts: parts.join(', ') }),
            detail,
            source: ti('research.chart.moveSource'),
            source_url: null,
        };
    });
}
