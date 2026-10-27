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

export function netMarginPoints(rawMarginPct: number, sectorMargin: number | null): number {
    const margin = percentToRatio(rawMarginPct);
    // V6: con benchmark NO positivo los multiplicadores se invierten (un
    // margen -15 % supera -10 % * 1,3 = -13 %) y premiaban perder igual o
    // mas que el sector. El tramo relativo maximo exige ademas margen
    // claramente positivo; superar un benchmark en perdidas solo suma el
    // tramo intermedio.
    // TRADEOFF documentado (review #2467): una empresa en perdidas puede
    // puntuar 30 por ser "menos mala" que su sector (-5 % vs -10 %), mas
    // que la misma empresa sin datos sectoriales (0). Es fuerza relativa
    // INTENCIONADA: el score compara contra pares. Cambiarlo (puntos solo
    // con margen > 0) es una decision de filosofia de scoring, no de
    // correccion; se deja al dueno del producto.
    if (sectorMargin !== null) {
        if (sectorMargin > 0) {
            if (margin > sectorMargin * 1.3) return 35;
            if (margin > sectorMargin) return 30;
        } else {
            if (margin > 0.1 && margin > sectorMargin) return 35;
            if (margin > sectorMargin) return 30;
        }
    }
    return margin > 0.1 ? 25 : margin > 0 ? 15 : 0;
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
export function revenueGrowthPoints(rawGrowthPct: number, sectorGrowth: number | null): number {
    const growth = percentToRatio(rawGrowthPct);
    // V6: misma inversion que netMarginPoints: con sector en contraccion,
    // crecer -12 % superaba -10 % * 1,5 = -15 % y recibia el maximo (40).
    // Mismo tradeoff de fuerza relativa documentado en netMarginPoints.
    if (sectorGrowth !== null) {
        if (sectorGrowth > 0) {
            if (growth > sectorGrowth * 1.5) return 40;
            if (growth > sectorGrowth) return 35;
        } else {
            if (growth > 0.1 && growth > sectorGrowth) return 40;
            if (growth > sectorGrowth) return 35;
        }
    }
    return growth > 0 ? 25 : 10;
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
