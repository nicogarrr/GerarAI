/**
 * Puntos del scoring avanzado que dependen de UNIDADES (rentabilidad, crecimiento, cambio diario).
 *
 * Módulo puro (sin alias ni E/S) para poder testearlo con node:test.
 *
 * Unidades: la única fuente es Finnhub (`/stock/metric?metric=all` y `/quote`, ver
 * getStockFinancialDataLight). Finnhub da márgenes, ROE, ROA y crecimientos en
 * PORCENTAJE (24,3 = 24,3 %; ROE de Apple ≈ 150) y `quote.dp` también en porcentaje
 * («Percent change»). Por eso se divide SIEMPRE entre 100: la heurística anterior
 * |x| > 1 ⇒ % leía un margen del 0,8 % como 80 %, y en los crecimientos se dividía
 * dos veces (150 % → 1,5 %).
 *
 * El signo se conserva: una pérdida es rentabilidad NEGATIVA, nunca positiva.
 * Referencia: CFA Institute, Financial Statement Analysis (margen neto = beneficio neto / ventas).
 */

/** Pasa a fracción un valor de Finnhub expresado en % (24,3 → 0,243), CONSERVANDO el signo. */
export function percentToRatio(value: number): number {
    return value / 100;
}

export function netMarginPoints(rawMarginPct: number, sectorMargin: number): number {
    const margin = percentToRatio(rawMarginPct);
    return margin > sectorMargin * 1.3 ? 35 : margin > sectorMargin ? 30 : margin > 0.1 ? 25 : margin > 0 ? 15 : 0;
}

export function roePoints(rawRoePct: number): number {
    const roe = percentToRatio(rawRoePct);
    return roe > 0.2 ? 35 : roe > 0.15 ? 30 : roe > 0.1 ? 25 : roe > 0 ? 20 : 10;
}

export function roaPoints(rawRoaPct: number): number {
    const roa = percentToRatio(rawRoaPct);
    return roa > 0.1 ? 30 : roa > 0.05 ? 25 : roa > 0 ? 20 : 10;
}

/** Crecimiento de ventas (en %) frente al del sector (en fracción). */
export function revenueGrowthPoints(rawGrowthPct: number, sectorGrowth: number): number {
    const growth = percentToRatio(rawGrowthPct);
    return growth > sectorGrowth * 1.5 ? 40 : growth > sectorGrowth ? 35 : growth > 0 ? 25 : 10;
}

export function epsGrowthPoints(rawGrowthPct: number): number {
    const growth = percentToRatio(rawGrowthPct);
    return growth > 0.2 ? 30 : growth > 0.1 ? 25 : growth > 0 ? 20 : 10;
}

export function ebitdaGrowthPoints(rawGrowthPct: number): number {
    const growth = percentToRatio(rawGrowthPct);
    return growth > 0.15 ? 30 : growth > 0 ? 20 : 10;
}

/**
 * Cambio del día (`quote.dp`, ya en %). Umbrales +1 % / +2 % y CON signo: una caída
 * fuerte no es impulso (antes |dp/100| > 2 nunca se cumplía y además premiaba la volatilidad).
 */
export function dailyChangePoints(dailyChangePct: number): number {
    return dailyChangePct > 2 ? 15 : dailyChangePct > 1 ? 10 : 5;
}
