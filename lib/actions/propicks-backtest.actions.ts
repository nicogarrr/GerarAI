'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getSafeErrorMessage } from '@/lib/types/errors';
import { getCandles } from '@/lib/actions/finnhub.actions';

/* ================================================================== */
/* Backtest walk-forward HONESTO (solo precios hasta cada corte).      */
/*                                                                     */
/* LIMITACIÓN CONOCIDA (documentada a propósito): la selección mes a   */
/* mes usa EXCLUSIVAMENTE features derivadas de precio disponibles     */
/* hasta cada corte (momentum 12-1M, momentum 6-1M y proximidad al     */
/* máximo de 52 semanas). Los fundamentales ACTUALES (métricas,        */
/* price-targets, scores) tienen look-ahead bias si se usan para el    */
/* pasado y por eso están PROHIBIDOS aquí: este backtest no pretende   */
/* replicar la selección fundamentalista en vivo, solo medir si la     */
/* rotación mensual por momentum/proximidad habría funcionado.         */
/*                                                                     */
/* Sistema de snapshots para un backtest verdadero futuro: cada mes se */
/* guarda en `snapshots` el { asOf, symbols, scores } seleccionado.    */
/* Ese array es descargable como JSON y es la semilla del futuro       */
/* backtest con fundamentales reales: cuando exista un almacén de      */
/* snapshots fundamentales point-in-time, se re-ejecutará la misma     */
/* selección sobre esos snapshots en vez de sobre features de precio.  */
/* ================================================================== */

export interface WalkForwardMonthRow {
    /** Corte de selección (fin de mes, ISO). Solo se usó precio <= asOf. */
    asOf: string;
    picks: string[];
    /** Retorno % del mes siguiente (bruto, equiponderado). */
    retBruto: number;
    /** Retorno % neto de costes de rotación (15pb por pata). */
    retNeto: number;
    /** Retorno % de SPY en el mismo mes. */
    spy: number;
    /** Rotación % (fracción de la cartera reemplazada x 100). */
    turnover: number;
}

export interface WalkForwardSnapshot {
    asOf: string;
    symbols: string[];
    scores: Record<string, number>;
}

export interface WalkForwardBacktestResult {
    months: number;
    picksPorMes: number;
    /** Rotación media mensual % (0-100). */
    turnover: number;
    /** Retorno total % compuesto bruto. */
    retornoBruto: number;
    /** Retorno total % compuesto neto de costes. */
    retornoNeto: number;
    /** Retorno total % de SPY (buy&hold mismo periodo). */
    spy: number;
    sharpe: number;
    sortino: number;
    /** Máximo drawdown sobre la curva neta, en puntos y con signo (<= 0: -8,12 = caída del 8,12 %). */
    maxDD: number;
    tablaMensual: WalkForwardMonthRow[];
    /** Semilla JSON para el futuro backtest con fundamentales reales. */
    snapshots: WalkForwardSnapshot[];
}

/**
 * Espejo CAPADO del LIQUID_UNIVERSE de proPicks.actions.ts (mismo orden,
 * primeros 30; no se puede importar porque no está exportado y está
 * prohibido tocar otros ficheros). Capado por límites de cómputo:
 * 31 series (30 + SPY) x 1 descarga cada una, sin bucles anidados.
 */
const WF_UNIVERSE: readonly string[] = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'AVGO', 'ORCL', 'CRM', 'AMD',
    'JPM', 'BAC', 'GS', 'MS', 'V', 'MA', 'AXP', 'BLK', 'SCHW', 'C',
    'LLY', 'UNH', 'JNJ', 'MRK', 'ABBV', 'TMO', 'ABT', 'ISRG', 'GILD', 'AMGN',
] as const;

const WF_MAX_MONTHS = 36;
const WF_DEFAULT_MONTHS = 12;
const WF_DEFAULT_TOP_N = 5;
const WF_MAX_TOP_N = 10;
const WF_COST_BPS_PER_LEG = 15; // 15pb por pata de rotación (venta y compra = 2 patas)
const WF_MIN_SESSIONS = 253; // 252 sesiones + la del corte
const WF_PREFETCH_DAYS = 420; // margen en días naturales para ~253 sesiones + festivos
const WF_BATCH = 8;

type PriceSeries = { t: number[]; c: number[] };

function wfMonthEndUTC(year: number, monthIdx: number): Date {
    return new Date(Date.UTC(year, monthIdx + 1, 0, 23, 59, 59));
}

function wfMean(values: number[]): number {
    if (values.length === 0) return 0;
    return values.reduce((s, v) => s + v, 0) / values.length;
}

function wfStd(values: number[]): number {
    if (values.length < 2) return 0;
    const m = wfMean(values);
    const variance = values.reduce((s, v) => s + (v - m) * (v - m), 0) / values.length;
    return Math.sqrt(Math.max(0, variance));
}

const wfPct2 = (fraction: number): number => Math.round(fraction * 10000) / 100;

/** Último índice con timestamp <= dateMs, o -1 si no hay. */
function wfPriceIndexAtOrBefore(series: PriceSeries, dateMs: number): number {
    let idx = -1;
    for (let i = 0; i < series.t.length; i++) {
        if (series.t[i] * 1000 <= dateMs) idx = i;
        else break; // las velas vienen ordenadas: corte temprano, sin bucle infinito
    }
    return idx;
}

/** Precio de cierre en/antes de la fecha, o null si no existe. */
function wfPriceAtOrBefore(series: PriceSeries, dateMs: number): number | null {
    const idx = wfPriceIndexAtOrBefore(series, dateMs);
    if (idx < 0) return null;
    const price = series.c[idx];
    return typeof price === 'number' && Number.isFinite(price) && price > 0 ? price : null;
}

function rankDesc(values: Map<string, number>): Map<string, number> {
    const sorted = [...values.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const ranks = new Map<string, number>();
    sorted.forEach(([symbol], i) => ranks.set(symbol, i + 1));
    return ranks;
}

export async function runWalkForwardBacktest(
    options?: { months?: number; topN?: number },
): Promise<WalkForwardBacktestResult | { error: string }> {
    try {
        await requireAuthenticatedUser();

        const months = Math.max(1, Math.min(WF_MAX_MONTHS, Math.floor(options?.months ?? WF_DEFAULT_MONTHS)));
        const topN = Math.max(1, Math.min(WF_MAX_TOP_N, Math.floor(options?.topN ?? WF_DEFAULT_TOP_N)));

        // Cortes: months+1 fines de mes, el último = último mes completo.
        const now = new Date();
        const base = wfMonthEndUTC(now.getUTCFullYear(), now.getUTCMonth() - 1);
        const baseY = base.getUTCFullYear();
        const baseM = base.getUTCMonth();
        const cutoffs: Date[] = [];
        for (let i = 0; i <= months; i++) {
            cutoffs.push(new Date(Date.UTC(baseY, baseM - (months - i) + 1, 0, 23, 59, 59)));
        }

        // UNA sola descarga por símbolo para todo el periodo; el corte
        // point-in-time se aplica al LEER (índices <= asOf), nunca al pedir.
        const from = Math.floor(cutoffs[0].getTime() / 1000) - WF_PREFETCH_DAYS * 86400;
        const to = Math.floor(cutoffs[months].getTime() / 1000) + 86400;
        const symbols = [...WF_UNIVERSE, 'SPY'];
        const series = new Map<string, PriceSeries>();
        for (let i = 0; i < symbols.length; i += WF_BATCH) {
            const batch = symbols.slice(i, i + WF_BATCH);
            const results = await Promise.all(
                batch.map(async (symbol) => {
                    const candles = await getCandles(symbol, from, to, 'D', 3600).catch(() => null);
                    return { symbol, candles };
                }),
            );
            for (const { symbol, candles } of results) {
                if (candles?.s === 'ok' && candles.c.length > 0) {
                    series.set(symbol, { t: candles.t, c: candles.c });
                }
            }
        }
        const spySeries = series.get('SPY') ?? null;

        const tablaMensual: WalkForwardMonthRow[] = [];
        const snapshots: WalkForwardSnapshot[] = [];
        let prevPicks: string[] = [];

        for (let k = 0; k < months; k++) {
            const asOfMs = cutoffs[k].getTime();
            const nextMs = cutoffs[k + 1].getTime();

            // Features SOLO con velas <= asOf (prohibido mirar el futuro).
            const mom12 = new Map<string, number>();
            const mom6 = new Map<string, number>();
            const prox = new Map<string, number>();
            for (const symbol of WF_UNIVERSE) {
                const s = series.get(symbol);
                if (!s) continue;
                const idx = wfPriceIndexAtOrBefore(s, asOfMs);
                if (idx < WF_MIN_SESSIONS) continue; // sin 252 sesiones: no elegible ese mes
                const priceNow = s.c[idx];
                const price1M = s.c[idx - 21];
                const price6M = s.c[idx - 126];
                const price12M = s.c[idx - 252];
                if (![priceNow, price1M, price6M, price12M].every((p) => typeof p === 'number' && Number.isFinite(p) && p > 0)) continue;
                let peak52 = 0;
                for (let j = idx - 252; j <= idx; j++) {
                    if (s.c[j] > peak52) peak52 = s.c[j];
                }
                if (!(peak52 > 0)) continue;
                mom12.set(symbol, price1M / price12M - 1); // momentum 12-1M (salta el último mes)
                mom6.set(symbol, price1M / price6M - 1); // momentum 6-1M
                prox.set(symbol, priceNow / peak52); // proximidad al máximo de 52 semanas
            }
            if (mom12.size === 0) continue;

            const r12 = rankDesc(mom12);
            const r6 = rankDesc(mom6);
            const rp = rankDesc(prox);
            const n = mom12.size;
            const rankOf = (m: Map<string, number>, symbol: string): number => m.get(symbol) ?? n + 1;
            const scored = [...mom12.keys()].map((symbol) => {
                const avgRank = (rankOf(r12, symbol) + rankOf(r6, symbol) + rankOf(rp, symbol)) / 3;
                return { symbol, avgRank, score: Math.round((1 - (avgRank - 1) / n) * 1000) / 10 };
            });
            scored.sort((a, b) => a.avgRank - b.avgRank || a.symbol.localeCompare(b.symbol));
            const picks = scored.slice(0, Math.min(topN, scored.length));

            // Retorno del mes siguiente por pick, con precios <= cada corte.
            const rets: number[] = [];
            for (const pick of picks) {
                const s = series.get(pick.symbol);
                if (!s) continue;
                const entry = wfPriceAtOrBefore(s, asOfMs);
                const exit = wfPriceAtOrBefore(s, nextMs);
                if (entry === null || exit === null) continue;
                rets.push(exit / entry - 1);
            }
            if (rets.length === 0) continue;

            const gross = wfMean(rets);
            const turnoverFrac = prevPicks.length === 0
                ? 1
                : picks.filter((p) => !prevPicks.includes(p.symbol)).length / picks.length;
            const cost = turnoverFrac * 2 * (WF_COST_BPS_PER_LEG / 10000);
            const net = gross - cost;

            let spyRet = 0;
            if (spySeries) {
                const spyEntry = wfPriceAtOrBefore(spySeries, asOfMs);
                const spyExit = wfPriceAtOrBefore(spySeries, nextMs);
                if (spyEntry !== null && spyExit !== null) spyRet = spyExit / spyEntry - 1;
            }

            const asOfIso = cutoffs[k].toISOString();
            const scores: Record<string, number> = {};
            for (const p of picks) scores[p.symbol] = p.score;
            snapshots.push({ asOf: asOfIso, symbols: picks.map((p) => p.symbol), scores });
            tablaMensual.push({
                asOf: asOfIso,
                picks: picks.map((p) => p.symbol),
                retBruto: wfPct2(gross),
                retNeto: wfPct2(net),
                spy: wfPct2(spyRet),
                turnover: wfPct2(turnoverFrac),
            });
            prevPicks = picks.map((p) => p.symbol);
        }

        if (tablaMensual.length === 0) {
            return { error: 'No hay datos de mercado suficientes para el backtest walk-forward' };
        }

        const grossW = tablaMensual.map((r) => r.retBruto / 100);
        const netW = tablaMensual.map((r) => r.retNeto / 100);
        const spyW = tablaMensual.map((r) => r.spy / 100);
        const compound = (rs: number[]): number => rs.reduce((acc, r) => acc * (1 + r), 1) - 1;

        const netStd = wfStd(netW);
        const downside = netW.filter((r) => r < 0);
        const downStd = downside.length > 0 ? Math.sqrt(downside.reduce((s, r) => s + r * r, 0) / netW.length) : 0;
        const netMean = wfMean(netW);
        const sharpe = netStd > 0 ? (netMean / netStd) * Math.sqrt(12) : 0;
        const sortino = downStd > 0 ? (netMean / downStd) * Math.sqrt(12) : 0;

        let peak = 1;
        let equity = 1;
        let maxDD = 0;
        for (const r of netW) {
            equity *= 1 + r;
            if (equity > peak) peak = equity;
            const dd = peak > 0 ? (peak - equity) / peak : 0;
            if (dd > maxDD) maxDD = dd;
        }

        return {
            months: tablaMensual.length,
            picksPorMes: Math.round(wfMean(tablaMensual.map((r) => r.picks.length)) * 10) / 10,
            turnover: wfPct2(wfMean(tablaMensual.map((r) => r.turnover / 100))),
            retornoBruto: wfPct2(compound(grossW)),
            retornoNeto: wfPct2(compound(netW)),
            spy: wfPct2(compound(spyW)),
            sharpe: Math.round(sharpe * 100) / 100,
            sortino: Math.round(sortino * 100) / 100,
            // Convención firmada como el backend (_drawdown) y /portfolio/intelligence:
            // maxDD <= 0, la pérdida se muestra con signo menos en toda la app.
            maxDD: wfPct2(-maxDD),
            tablaMensual,
            snapshots,
        };
    } catch (error) {
        console.error('Error ejecutando backtest walk-forward:', error);
        return { error: getSafeErrorMessage(error) };
    }
}