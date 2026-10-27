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

