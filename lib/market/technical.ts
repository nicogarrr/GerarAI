/** Deterministic daily-bar indicators. No quote is mixed into historical bars. */
export type TechnicalBar = { date: string; close: number; open?: number | null; high?: number | null; low?: number | null; volume: number | null };
export type ChartRange = '1M' | '6M' | 'YTD' | '1A';
export function cleanBars(history: readonly TechnicalBar[]): TechnicalBar[] {
    const dates = new Map<string, TechnicalBar>();
    for (const bar of history) {
        const epoch = Date.parse(`${bar.date}T00:00:00Z`);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(bar.date) || !Number.isFinite(epoch) || new Date(epoch).toISOString().slice(0, 10) !== bar.date || !Number.isFinite(bar.close) || bar.close <= 0) continue;
        dates.set(bar.date, bar);
    }
    return [...dates.values()].sort((a, b) => a.date.localeCompare(b.date));
}

/** Window anchored to the last bar, not to an invented live timestamp. */
export function rangeBars(bars: readonly TechnicalBar[], range: ChartRange): TechnicalBar[] {
    if (!bars.length) return [];
    const end = new Date(`${bars.at(-1)!.date}T00:00:00Z`);
    const start = new Date(end);
    if (range === 'YTD') start.setUTCMonth(0, 1);
    else start.setUTCDate(start.getUTCDate() - (range === '1M' ? 31 : range === '6M' ? 183 : 366));
    return bars.filter((bar) => bar.date >= start.toISOString().slice(0, 10));
}

export function hasOHLC(bar: TechnicalBar): boolean {
    const { open, high, low, close } = bar;
    return [open, high, low].every((v) => typeof v === 'number' && Number.isFinite(v) && v > 0) && high! >= Math.max(open!, close) && low! <= Math.min(open!, close) && high! >= low!;
}

export function dailyPivots(bars: readonly TechnicalBar[]) {
    // Last observed daily bar: reference levels, NOT confirmed turning points.
    const bar = bars.at(-1);
    if (!bar || !hasOHLC(bar)) return [];
    const pivot = (bar.high! + bar.low! + bar.close) / 3;
    const span = bar.high! - bar.low!;
    return [
        { label: 'R2', price: pivot + span, kind: 'resistance' },
        { label: 'R1', price: 2 * pivot - bar.low!, kind: 'resistance' },
        { label: 'S1', price: 2 * pivot - bar.high!, kind: 'support' },
        { label: 'S2', price: pivot - span, kind: 'support' },
    ].filter((level) => level.price > 0);
}

export function sma(bars: readonly TechnicalBar[], period: number): number | null {
    if (!Number.isInteger(period) || period <= 0 || bars.length < period) return null;
    return bars.slice(-period).reduce((sum, bar) => sum + bar.close, 0) / period;
}

/** Wilder ADX: seed TR/DM with n transitions, then seed ADX with n DX values. */
export function adx(bars: readonly TechnicalBar[], period = 14): number | null {
    if (!Number.isInteger(period) || period < 2 || bars.length < 2 * period || !bars.every(hasOHLC)) return null;
    let tr = 0, plus = 0, minus = 0;
    const dx: number[] = [];
    for (let i = 1; i < bars.length; i++) {
        const prev = bars[i - 1], bar = bars[i];
        const up = bar.high! - prev.high!, down = prev.low! - bar.low!;
        const nextTR = Math.max(bar.high! - bar.low!, Math.abs(bar.high! - prev.close), Math.abs(bar.low! - prev.close));
        const nextPlus = up > down && up > 0 ? up : 0;
        const nextMinus = down > up && down > 0 ? down : 0;
        if (i <= period) { tr += nextTR; plus += nextPlus; minus += nextMinus; }
        else { tr = tr - tr / period + nextTR; plus = plus - plus / period + nextPlus; minus = minus - minus / period + nextMinus; }
        if (i >= period) {
            const total = plus + minus;
            dx.push(tr > 0 && total > 0 ? 100 * Math.abs(plus - minus) / total : 0);
        }
    }
    if (dx.length < period) return null;
    let value = dx.slice(0, period).reduce((sum, v) => sum + v, 0) / period;
    for (const v of dx.slice(period)) value = (value * (period - 1) + v) / period;
    return value;
}

/** Compare the latest two non-overlapping 10-session high/low windows. */
export function structure(bars: readonly TechnicalBar[]): 'Alcista' | 'Bajista' | 'Mixta' | 'Sin datos' {
    const sample = bars.slice(-20);
    if (sample.length < 20 || !sample.every(hasOHLC)) return 'Sin datos';
    const previous = sample.slice(0, 10), recent = sample.slice(10);
    const high = (group: TechnicalBar[]) => Math.max(...group.map((bar) => bar.high!));
    const low = (group: TechnicalBar[]) => Math.min(...group.map((bar) => bar.low!));
    if (high(recent) > high(previous) && low(recent) > low(previous)) return 'Alcista';
    if (high(recent) < high(previous) && low(recent) < low(previous)) return 'Bajista';
    return 'Mixta';
}

/** Retracements from the observed visible low/high, no claimed swing direction. */
export function fibonacci(bars: readonly TechnicalBar[]) {
    if (bars.length < 2 || !bars.every(hasOHLC)) return [];
    const low = Math.min(...bars.map((bar) => bar.low!));
    const high = Math.max(...bars.map((bar) => bar.high!));
    if (high <= low) return [];
    return [0.236, 0.382, 0.5, 0.618, 0.786].map((ratio) => ({ ratio, price: high - (high - low) * ratio }));
}
