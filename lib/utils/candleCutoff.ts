/**
 * Corte temporal de velas para scoring/valoración point-in-time (V3).
 *
 * Módulo puro (sin alias ni E/S) para poder testearlo con node:test.
 *
 * `dates` viene en SEGUNDOS Unix (contrato Finnhub /stock/candle) y `asOf` en
 * ISO. Una vela con t <= corte entra; una posterior se excluye SIEMPRE: el
 * corte filtra, no etiqueta. Con un corte inválido (no parseable) se devuelve
 * la serie intacta y lo decide el llamador: filtrar con un corte roto sería
 * peor que no filtrar.
 */

export interface CandleSeries {
    prices: number[];
    dates: number[];
}

export function filterCandlesUpTo(series: CandleSeries, asOf: string): CandleSeries {
    const cutoffMs = Date.parse(asOf);
    if (!Number.isFinite(cutoffMs)) {
        return series;
    }
    const cutoffSec = cutoffMs / 1000;
    const prices: number[] = [];
    const dates: number[] = [];
    const length = Math.min(series.prices.length, series.dates.length);
    for (let i = 0; i < length; i++) {
        if (series.dates[i] <= cutoffSec) {
            dates.push(series.dates[i]);
            prices.push(series.prices[i]);
        }
    }
    return { prices, dates };
}
