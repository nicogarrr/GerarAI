/**
 * Velas + volumen para lightweight-charts v5 (TradingView).
 *
 * Módulo PURO: sin imports de servidor ni de la librería de charts, para
 * poder probarlo con `node --test`. La librería solo se carga en cliente
 * (import dinámico dentro del componente).
 *
 * Honestidad de datos (F318 paradigm): una sesión sin OHLC completo NO entra
 * en las velas (una vela inventada con O=H=L=C parece volatilidad cero y es
 * peor que un estado vacío explícito) y un volumen desconocido (null) NO
 * entra en el histograma (nunca un 0 fabricado).
 */

import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';

/** Serie del workspace más el OHLC que el backend ya sirve en cada vela. */
export type MarketHistoryPoint = CompanyMarketSnapshot['history'][number] & {
    open?: number | null;
    high?: number | null;
    low?: number | null;
};

/** Fila lista para lightweight-charts: tiempo BusinessDay `YYYY-MM-DD`. */
export type CandleRow = {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    /** null = volumen desconocido (se omite en el histograma, nunca 0). */
    volume: number | null;
};

/** Enlace exigido por la cláusula de atribución de la licencia. */
export const TRADINGVIEW_URL = 'https://www.tradingview.com/';

const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Filtra sesiones con OHLC completo y finito, ordena ascendentemente por
 * fecha y deduplica (la última occurrence gana). El orden ascendente y los
 * tiempos únicos los exige la librería (puntos desordenados se descartan).
 */
export function toCandleRows(history: readonly MarketHistoryPoint[]): CandleRow[] {
    const byTime = new Map<string, CandleRow>();
    for (const point of history) {
        if (!point || typeof point.date !== 'string' || !DATE_ONLY_RE.test(point.date)) continue;
        const { open, high, low, close } = point;
        if (!isFiniteNumber(open) || !isFiniteNumber(high) || !isFiniteNumber(low) || !isFiniteNumber(close)) {
            continue;
        }
        const volume =
            point.volume === null || point.volume === undefined
                ? null
                : isFiniteNumber(point.volume)
                  ? point.volume
                  : null;
        byTime.set(point.date, { time: point.date, open, high, low, close, volume });
    }
    return [...byTime.values()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
}

/** Subconjunto OHLC para `CandlestickSeries.setData`. */
export function toCandlestickData(rows: readonly CandleRow[]): Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
}> {
    return rows.map(({ time, open, high, low, close }) => ({ time, open, high, low, close }));
}

/**
 * Histograma de volumen para `HistogramSeries.setData`. Las sesiones con
 * volumen desconocido se omiten (F318); el color sigue a la vela
 * (cierre >= apertura = alcista).
 */
export function toVolumeData(
    rows: readonly CandleRow[],
    colors: { up: string; down: string },
): Array<{ time: string; value: number; color: string }> {
    const data: Array<{ time: string; value: number; color: string }> = [];
    for (const row of rows) {
        if (row.volume === null) continue;
        data.push({
            time: row.time,
            value: row.volume,
            color: row.close >= row.open ? colors.up : colors.down,
        });
    }
    return data;
}

export type CandlesSummary = {
    count: number;
    firstTime: string;
    lastTime: string;
    lastClose: number;
    /** Cierre último menos cierre primero (base del resumen accesible). */
    change: number;
    /** En tanto por ciento; null si la base es 0 (no se aparenta). */
    changePercent: number | null;
    rangeHigh: number;
    rangeLow: number;
    /** Sesiones con volumen conocido (para rotular su ausencia). */
    knownVolumeSessions: number;
};

/** Resumen numérico para el `aria-label` y el pie (el formato lo pone la UI). */
export function summarizeCandles(rows: readonly CandleRow[]): CandlesSummary | null {
    if (rows.length === 0) return null;
    const first = rows[0];
    const last = rows[rows.length - 1];
    let rangeHigh = Number.NEGATIVE_INFINITY;
    let rangeLow = Number.POSITIVE_INFINITY;
    let knownVolumeSessions = 0;
    for (const row of rows) {
        if (row.high > rangeHigh) rangeHigh = row.high;
        if (row.low < rangeLow) rangeLow = row.low;
        if (row.volume !== null) knownVolumeSessions += 1;
    }
    const change = last.close - first.close;
    return {
        count: rows.length,
        firstTime: first.time,
        lastTime: last.time,
        lastClose: last.close,
        change,
        changePercent: first.close !== 0 ? (change / Math.abs(first.close)) * 100 : null,
        rangeHigh,
        rangeLow,
        knownVolumeSessions,
    };
}
