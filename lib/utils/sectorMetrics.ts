/** Frontera del contrato porcentual usado por el scoring de empresa.
 * Salidas ROE/ROA/margen/crecimiento en fraccion (15% = 0.15).
 * No afirma verificacion de datos actuales del proveedor.
 */
export function calculateAverage(metrics: Record<string, unknown>[], metricNames: string[], unit: 'ratio' | 'percent' = 'ratio'): number | null {
    const values: number[] = [];

    for (const metric of metrics) {
        for (const name of metricNames) {
            const value = metric[name];
            if (value !== null && value !== undefined && value !== '') {
                const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : Number(value);
                if (Number.isFinite(num)) {
                    // Contrato explicito por campo; nunca inferir por magnitud o alias.
                    const normalized = unit === 'percent' ? num / 100 : num;
                    values.push(normalized);
                    break;
                }
            }
        }
    }

    if (values.length === 0) return null;
    return values.reduce((a, b) => a + b, 0) / values.length;
}


export function normalizeGrowthScore(revenueGrowth: number): number {
    const growth = revenueGrowth;
    
    if (growth > 0.2) return 90;
    if (growth > 0.15) return 80;
    if (growth > 0.1) return 70;
    if (growth > 0.05) return 60;
    if (growth > 0) return 50;
    return 30;
}

/**
 * Normaliza score de rentabilidad (0-100)
 */
export function normalizeProfitabilityScore(netMargin: number, roe: number, roa: number): number {
    let score = 0;
    
    const margin = netMargin;
    if (margin > 0.2) score += 35;
    else if (margin > 0.15) score += 30;
    else if (margin > 0.1) score += 25;
    else if (margin > 0.05) score += 20;
    else if (margin > 0) score += 15;
    
    const roeValue = roe;
    if (roeValue > 0.2) score += 35;
    else if (roeValue > 0.15) score += 30;
    else if (roeValue > 0.1) score += 25;
    else if (roeValue > 0.05) score += 20;
    else if (roeValue > 0) score += 15;
    
    const roaValue = roa;
    if (roaValue > 0.1) score += 30;
    else if (roaValue > 0.05) score += 25;
    else if (roaValue > 0) score += 20;
    
    return Math.min(100, score);
}


/**
 * Normaliza score de valor (0-100) con PE/PB/PS en bandas absolutas.
 * Fórmula COMÚN empresa/sector (V7): el delta `vsSector` solo es honesto si
 * ambos lados usan la misma fórmula y el mismo conjunto de métricas.
 */
export function normalizeValueScore(pe: number, pb: number, ps: number): number {
    let score = 0;

    // PE: más bajo es mejor (invertir)
    if (pe > 0) {
        if (pe < 15) score += 35;
        else if (pe < 25) score += 30;
        else if (pe < 35) score += 25;
        else score += 15;
    }

    // PB: más bajo es mejor
    if (pb > 0) {
        if (pb < 2) score += 35;
        else if (pb < 4) score += 30;
        else if (pb < 6) score += 25;
        else score += 15;
    }

    // PS: más bajo es mejor
    if (ps > 0) {
        if (ps < 3) score += 30;
        else if (ps < 6) score += 25;
        else score += 15;
    }

    return Math.min(100, score);
}

/**
 * Normaliza score de deuda/liquidez (0-100). Fórmula COMÚN empresa/sector (V7).
 */
export function normalizeDebtScore(debtToEquity: number, currentRatio: number): number {
    let score = 0;

    const dte = Math.abs(debtToEquity);
    // D/E más bajo es mejor, pero depende del sector
    if (dte < 0.5) score += 40;
    else if (dte < 1) score += 35;
    else if (dte < 2) score += 30;
    else if (dte < 3) score += 25;
    else score += 15;

    // Current Ratio más alto es mejor
    if (currentRatio > 2) score += 30;
    else if (currentRatio > 1.5) score += 25;
    else if (currentRatio > 1) score += 20;
    else score += 10;

    return Math.min(100, score);
}

/**
 * Métricas compartidas empresa/sector para una comparación like-for-like.
 * Contrato de unidades: márgenes, ROE, ROA y crecimiento en FRACCIÓN
 * (15 % = 0.15); múltiplos y ratios sin escala. `null` = dato ausente.
 */
export interface ComparableMetricSet {
    pe: number | null;
    pb: number | null;
    ps: number | null;
    revenueGrowth: number | null;
    netMargin: number | null;
    roe: number | null;
    roa: number | null;
    debtToEquity: number | null;
    currentRatio: number | null;
}

export interface ComparableCategoryScores {
    value: number | null;
    growth: number | null;
    profitability: number | null;
    cashFlow: number | null;
    momentum: number | null;
    debtLiquidity: number | null;
}

/**
 * Scores de categoría con la fórmula COMÚN de comparación sectorial (V7).
 *
 * El score absoluto de la empresa (`categoryScores`) usa más métricas y es
 * cosa del scorer; ESTA función existe para que `vsSector` reste scores
 * calculados con la MISMA fórmula y el MISMO conjunto de métricas en ambos
 * lados (el sector no tiene EV/EBITDA, EPS/EBITDA growth, quick ratio ni
 * cobertura de intereses). Si falta una métrica en un lado, la categoría
 * queda null: desconocido honesto, no empate inventado.
 *
 * cashFlow y momentum no tienen datos sectoriales: siempre null.
 */
export function computeComparableCategoryScores(m: ComparableMetricSet): ComparableCategoryScores {
    return {
        value: m.pe === null || m.pb === null || m.ps === null
            ? null
            : normalizeValueScore(m.pe, m.pb, m.ps),
        growth: m.revenueGrowth === null ? null : normalizeGrowthScore(m.revenueGrowth),
        profitability: m.netMargin === null || m.roe === null || m.roa === null
            ? null
            : normalizeProfitabilityScore(m.netMargin, m.roe, m.roa),
        cashFlow: null, // Sin datos sectoriales de FCF
        momentum: null, // Sin datos históricos sectoriales
        debtLiquidity: m.debtToEquity === null || m.currentRatio === null
            ? null
            : normalizeDebtScore(m.debtToEquity, m.currentRatio),
    };
}
