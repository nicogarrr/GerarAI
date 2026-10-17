'use server';

import { cache } from 'react';
import { fetchJSON } from '@/lib/upstream/finnhub';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const FINNHUB_BASE_URL = 'https://finnhub.io/api/v1';

/**
 * Obtiene promedios del sector desde Finnhub (si está disponible)
 * o calcula promedios basándose en un conjunto de acciones del sector
 */
export interface SectorAverages {
    sector: string;
    averages: {
        value: number;          // 0-100
        growth: number;         // 0-100
        profitability: number; // 0-100
        cashFlow: number;       // 0-100
        momentum: number;       // 0-100
        debtLiquidity: number; // 0-100
    };
    sampleSize: number;
    metrics: {
        avgPE: number;
        avgPB: number;
        avgPS: number;
        avgROE: number;
        avgROA: number;
        avgNetMargin: number;
        avgRevenueGrowth: number;
        avgDebtToEquity: number;
        avgCurrentRatio: number;
    };
}

/**
 * Obtiene símbolos representativos de un sector
 */
const SECTOR_REPRESENTATIVE_STOCKS: Record<string, string[]> = {
    'Technology': ['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META', 'AMD', 'INTC', 'CRM', 'ORCL', 'ADBE'],
    'Financial Services': ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW'],
    'Healthcare': ['JNJ', 'PFE', 'UNH', 'ABBV', 'MRK', 'TMO', 'ABT', 'DHR'],
    'Consumer Cyclical': ['AMZN', 'HD', 'NKE', 'MCD', 'SBUX', 'NFLX', 'TSLA'],
    'Consumer Defensive': ['WMT', 'PG', 'KO', 'PEP', 'COST'],
    'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'EOG'],
    'Industrial': ['BA', 'CAT', 'GE', 'HON', 'UNP'],
    'Communication Services': ['GOOGL', 'META', 'NFLX', 'DIS', 'VZ'],
    'Utilities': ['NEE', 'DUK', 'SO', 'D', 'AEP'],
    'Real Estate': ['AMT', 'EQIX', 'PLD', 'PSA', 'WELL'],
    'Materials': ['LIN', 'APD', 'FCX', 'NEM', 'SHW'],
};

/**
 * Calcula promedios del sector basándose en acciones representativas
 */
export const getSectorAverages = cache(async (sector: string): Promise<SectorAverages | null> => {
    await requireAuthenticatedUser();
    try {
        const token = process.env.FINNHUB_API_KEY;
        if (!token) {
            // Sin API key, no podemos obtener datos reales
            console.warn(`No hay API key de Finnhub configurada. No se pueden obtener datos del sector ${sector}`);
            return null;
        }

        const representativeStocks = SECTOR_REPRESENTATIVE_STOCKS[sector] || [];
        
        if (representativeStocks.length === 0) {
            console.warn(`No hay acciones representativas definidas para el sector ${sector}`);
            return null;
        }

        // Obtener métricas de hasta 10 acciones representativas del sector
        const stocksToAnalyze = representativeStocks.slice(0, 10);
        const metrics: any[] = [];

        for (const symbol of stocksToAnalyze) {
            try {
                const metricsUrl = `${FINNHUB_BASE_URL}/stock/metric?symbol=${encodeURIComponent(symbol)}&metric=all&token=${token}`;
                const stockMetrics = await fetchJSON<any>(metricsUrl, 3600).catch(() => null);
                
                if (stockMetrics?.metric) {
                    metrics.push(stockMetrics.metric);
                }

                // Delay para evitar rate limiting
                await new Promise(resolve => setTimeout(resolve, 200));
            } catch {
                // Continuar con siguiente acción
                continue;
            }
        }

        if (metrics.length === 0) {
            console.warn(`No se pudieron obtener métricas del sector ${sector} desde la API`);
            return null;
        }

        // Calcular promedios
        const avgPE = calculateAverage(metrics, ['peTTM', 'pe', 'priceToEarnings']);
        const avgPB = calculateAverage(metrics, ['pbTTM', 'pb', 'priceToBook']);
        const avgPS = calculateAverage(metrics, ['psTTM', 'ps', 'priceToSales']);
        const avgROE = calculateAverage(metrics, ['roeTTM', 'roe', 'returnOnEquity']);
        const avgROA = calculateAverage(metrics, ['roaTTM', 'roa', 'returnOnAssets']);
        const avgNetMargin = calculateAverage(metrics, ['netProfitMarginTTM', 'netProfitMargin', 'profitMargin']);
        const avgRevenueGrowth = calculateAverage(metrics, ['revenueGrowthTTM', 'revenueGrowth', 'salesGrowth']);
        const avgDebtToEquity = calculateAverage(metrics, ['debtToEquityTTM', 'debtToEquity', 'totalDebtToEquity']);
        const avgCurrentRatio = calculateAverage(metrics, ['currentRatioTTM', 'currentRatio']);

        // Normalizar promedios a 0-100 para cada categoría
        const averages = {
            value: normalizeValueScore(avgPE || 25, avgPB || 3, avgPS || 5),
            growth: normalizeGrowthScore(avgRevenueGrowth || 0),
            profitability: normalizeProfitabilityScore(avgNetMargin || 0.15, avgROE || 0.15, avgROA || 0.08),
            cashFlow: 50, // Por defecto, necesitaríamos FCF que no está siempre disponible
            momentum: 50, // Por defecto, necesitaríamos datos históricos
            debtLiquidity: normalizeDebtScore(avgDebtToEquity || 1.5, avgCurrentRatio || 1.5),
        };

        return {
            sector,
            averages,
            sampleSize: metrics.length,
            metrics: {
                avgPE: avgPE || 0,
                avgPB: avgPB || 0,
                avgPS: avgPS || 0,
                avgROE: avgROE || 0,
                avgROA: avgROA || 0,
                avgNetMargin: avgNetMargin || 0,
                avgRevenueGrowth: avgRevenueGrowth || 0,
                avgDebtToEquity: avgDebtToEquity || 0,
                avgCurrentRatio: avgCurrentRatio || 0,
            },
        };
    } catch (error) {
        console.error(`Error getting sector averages for ${sector}:`, error);
        return getDefaultSectorAverages(sector);
    }
});

/**
 * Calcula promedio de una métrica buscando en diferentes nombres posibles
 */
function calculateAverage(metrics: any[], metricNames: string[]): number | null {
    const values: number[] = [];

    for (const metric of metrics) {
        for (const name of metricNames) {
            const value = metric[name];
            if (value !== null && value !== undefined && value !== '') {
                const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : Number(value);
                if (!isNaN(num)) {
                    // Normalizar si viene en porcentaje
                    const normalized = Math.abs(num) > 1 && name.includes('Growth') || name.includes('Margin') || name.includes('RO') ? num / 100 : num;
                    values.push(normalized);
                    break;
                }
            }
        }
    }

    if (values.length === 0) return null;
    return values.reduce((a, b) => a + b, 0) / values.length;
}

/**
 * Normaliza score de valor (0-100)
 */
function normalizeValueScore(pe: number, pb: number, ps: number): number {
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
 * Normaliza score de crecimiento (0-100)
 */
function normalizeGrowthScore(revenueGrowth: number): number {
    const growth = Math.abs(revenueGrowth) > 1 ? revenueGrowth / 100 : revenueGrowth;
    
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
function normalizeProfitabilityScore(netMargin: number, roe: number, roa: number): number {
    let score = 0;
    
    const margin = Math.abs(netMargin) > 1 ? netMargin / 100 : netMargin;
    if (margin > 0.2) score += 35;
    else if (margin > 0.15) score += 30;
    else if (margin > 0.1) score += 25;
    else if (margin > 0.05) score += 20;
    else if (margin > 0) score += 15;
    
    const roeValue = Math.abs(roe) > 1 ? roe / 100 : roe;
    if (roeValue > 0.2) score += 35;
    else if (roeValue > 0.15) score += 30;
    else if (roeValue > 0.1) score += 25;
    else if (roeValue > 0.05) score += 20;
    else if (roeValue > 0) score += 15;
    
    const roaValue = Math.abs(roa) > 1 ? roa / 100 : roa;
    if (roaValue > 0.1) score += 30;
    else if (roaValue > 0.05) score += 25;
    else if (roaValue > 0) score += 20;
    
    return Math.min(100, score);
}

/**
 * Normaliza score de deuda/liquidez (0-100)
 */
function normalizeDebtScore(debtToEquity: number, currentRatio: number): number {
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
 * Retorna null cuando no hay datos disponibles del sector
 * IMPORTANTE: Nunca inventamos datos. Si no hay datos reales, retornamos null
 */
function getDefaultSectorAverages(sector: string): SectorAverages | null {
    // Si no hay datos disponibles de la API, retornar null
    // Los componentes deben manejar este caso mostrando "Datos no disponibles"
    console.warn(`No se pudieron obtener datos del sector ${sector} desde la API. Retornando null para evitar datos inventados.`);
    return null;
}

