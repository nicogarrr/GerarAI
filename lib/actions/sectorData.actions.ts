'use server';

import { cache } from 'react';
import {
    calculateAverage,
    normalizeDebtScore,
    normalizeGrowthScore,
    normalizeProfitabilityScore,
    normalizeValueScore,
} from '@/lib/utils/sectorMetrics';
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
        value: number | null;          // 0-100
        growth: number | null;         // 0-100
        profitability: number | null; // 0-100
        cashFlow: number | null;       // 0-100
        momentum: number | null;       // 0-100
        debtLiquidity: number | null; // 0-100
    };
    sampleSize: number;
    unitTrace: {
        inputPercentageUnit: 'assumed_percent_not_provider_verified';
        outputPercentageUnit: 'fraction';
        missing: 'null';
    };
    metrics: {
        avgPE: number | null;
        avgPB: number | null;
        avgPS: number | null;
        // Fracciones: 15% = 0.15; nunca porcentajes crudos.
        avgROE: number | null;
        avgROA: number | null;
        avgNetMargin: number | null;
        avgRevenueGrowth: number | null;
        avgDebtToEquity: number | null;
        avgCurrentRatio: number | null;
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
        const metrics: Array<Record<string, unknown>> = [];

        for (const symbol of stocksToAnalyze) {
            try {
                const metricsUrl = `${FINNHUB_BASE_URL}/stock/metric?symbol=${encodeURIComponent(symbol)}&metric=all&token=${token}`;
                const stockMetrics = await fetchJSON<{ metric?: Record<string, unknown> }>(metricsUrl, 3600).catch(() => null);
                
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
        const avgROE = calculateAverage(metrics, ['roeTTM', 'roe', 'returnOnEquity'], 'percent');
        const avgROA = calculateAverage(metrics, ['roaTTM', 'roa', 'returnOnAssets'], 'percent');
        const avgNetMargin = calculateAverage(metrics, ['netProfitMarginTTM', 'netProfitMargin', 'profitMargin'], 'percent');
        const avgRevenueGrowth = calculateAverage(metrics, ['revenueGrowthTTM', 'revenueGrowth', 'salesGrowth'], 'percent');
        const avgDebtToEquity = calculateAverage(metrics, ['debtToEquityTTM', 'debtToEquity', 'totalDebtToEquity']);
        const avgCurrentRatio = calculateAverage(metrics, ['currentRatioTTM', 'currentRatio']);

        // Normalizar promedios a 0-100 para cada categoría
        const averages = {
            value: avgPE === null || avgPB === null || avgPS === null ? null : normalizeValueScore(avgPE, avgPB, avgPS),
            growth: avgRevenueGrowth === null ? null : normalizeGrowthScore(avgRevenueGrowth),
            profitability: avgNetMargin === null || avgROE === null || avgROA === null ? null : normalizeProfitabilityScore(avgNetMargin, avgROE, avgROA),
            cashFlow: null, // Sin datos sectoriales de FCF
            momentum: null, // Sin datos historicos sectoriales
            debtLiquidity: avgDebtToEquity === null || avgCurrentRatio === null ? null : normalizeDebtScore(avgDebtToEquity, avgCurrentRatio),
        };

        return {
            sector,
            averages,
            sampleSize: metrics.length,
            unitTrace: {
                inputPercentageUnit: 'assumed_percent_not_provider_verified',
                outputPercentageUnit: 'fraction',
                missing: 'null',
            },
            metrics: {
                avgPE: avgPE,
                avgPB: avgPB,
                avgPS: avgPS,
                avgROE: avgROE,
                avgROA: avgROA,
                avgNetMargin: avgNetMargin,
                avgRevenueGrowth: avgRevenueGrowth,
                avgDebtToEquity: avgDebtToEquity,
                avgCurrentRatio: avgCurrentRatio,
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

/**
 * Normaliza score de crecimiento (0-100)
 */

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

