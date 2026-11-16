/**
 * Estrategias ProPicks - Similar a Investing Pro
 *
 * Cada estrategia aplica filtros específicos usando el modelo de scoring avanzado
 */

import type { AdvancedScoreData } from './advancedStockScoring';

export interface ProPickStrategy {
    id: string;
    name: string;
    description: string;
    categoryWeights: {
        value: number;
        growth: number;
        profitability: number;
        cashFlow: number;
        momentum: number;
        debtLiquidity: number;
    };
    filters: {
        minScore?: number;
        minCategoryScores?: Partial<AdvancedScoreData['categoryScores']>;
        sectors?: string[];
        maxPrice?: number;
        minMarketCap?: number;
    };
}

/**
 * Estrategia única adaptativa - La IA selecciona las mejores acciones según datos reales actuales
 *
 * Pesos calibrados (suman 1.0): valor 20% + crecimiento 20% + rentabilidad 20% +
 * flujo de caja 15% + momentum 15% + deuda/liquidez 10%.
 * Fórmula: strategyScore = round(Σ categoría_i × peso_i).
 * Difiere del score general (que pondera rentabilidad 25% y momentum 10%):
 * la estrategia adaptativa equilibra valor/crecimiento/rentabilidad a partes
 * iguales para rotar entre estilos según el momento de mercado.
 */
export const PROPICKS_STRATEGIES: ProPickStrategy[] = [
    {
        id: 'adaptive',
        name: 'Selección Adaptativa IA',
        description: 'La IA analiza datos reales actuales del mercado y selecciona las mejores oportunidades en cada momento',
        categoryWeights: {
            value: 0.20,
            growth: 0.20,
            profitability: 0.20,
            cashFlow: 0.15,
            momentum: 0.15,
            debtLiquidity: 0.10,
        },
        filters: {
            // Sin filtros estrictos - la IA decide basándose en datos reales
            minScore: 60,
        },
    },
    {
        id: 'value',
        name: 'Calidad-valor (spread CFROI-WACC)',
        description: 'Rentabilidad del capital por encima de su coste: prima el spread CFROI-WACC y la calidad con exigencia de caja y balance. No es valoración por múltiplos: el componente «value» del embudo mide ese spread, no lo barata que está la acción',
        categoryWeights: {
            value: 0.35,
            growth: 0.05,
            profitability: 0.25,
            cashFlow: 0.15,
            momentum: 0.05,
            debtLiquidity: 0.15,
        },
        filters: {
            minScore: 60,
        },
    },
    {
        id: 'momentum',
        name: 'Momentum',
        description: 'Tendencia y crecimiento: prima el impulso y el crecimiento con apoyo de rentabilidad y valor',
        categoryWeights: {
            value: 0.10,
            growth: 0.25,
            profitability: 0.15,
            cashFlow: 0.10,
            momentum: 0.40,
            debtLiquidity: 0,
        },
        filters: {
            minScore: 65,
        },
    },
    {
        id: 'defensiva',
        name: 'Defensiva',
        description: 'Calidad y balance: prima la rentabilidad, la salud financiera y la caja para aguantar caídas del mercado',
        categoryWeights: {
            value: 0.15,
            growth: 0.05,
            profitability: 0.30,
            cashFlow: 0.20,
            momentum: 0.05,
            debtLiquidity: 0.25,
        },
        filters: {
            minScore: 65,
        },
    },
];

/**
 * Obtiene una estrategia por ID
 */
export function getStrategyById(id: string): ProPickStrategy | undefined {
    return PROPICKS_STRATEGIES.find(s => s.id === id);
}

/**
 * Calcula score ponderado según estrategia
 */
export function calculateStrategyScore(
    advancedScore: AdvancedScoreData,
    strategy: ProPickStrategy
): number {
    const { categoryScores } = advancedScore;
    const { categoryWeights } = strategy;

    return Math.round(
        categoryScores.value * categoryWeights.value +
        categoryScores.growth * categoryWeights.growth +
        categoryScores.profitability * categoryWeights.profitability +
        categoryScores.cashFlow * categoryWeights.cashFlow +
        categoryScores.momentum * categoryWeights.momentum +
        categoryScores.debtLiquidity * categoryWeights.debtLiquidity
    );
}

/**
 * Verifica si una acción pasa los filtros de una estrategia
 */
export function passesStrategyFilters(
    advancedScore: AdvancedScoreData,
    strategy: ProPickStrategy,
    sector?: string,
    price?: number,
    marketCap?: number
): boolean {
    const { filters } = strategy;

    // Verificar score mínimo
    if (filters.minScore && advancedScore.overallScore < filters.minScore) {
        return false;
    }

    // Verificar scores mínimos por categoría
    if (filters.minCategoryScores) {
        for (const [category, minScore] of Object.entries(filters.minCategoryScores)) {
            if (advancedScore.categoryScores[category as keyof typeof advancedScore.categoryScores] < minScore!) {
                return false;
            }
        }
    }

    // Verificar sector
    if (filters.sectors && sector && !filters.sectors.includes(sector)) {
        return false;
    }

    // Verificar precio máximo
    if (filters.maxPrice && price && price > filters.maxPrice) {
        return false;
    }

    // Verificar market cap mínimo
    if (filters.minMarketCap && marketCap && marketCap < filters.minMarketCap) {
        return false;
    }

    return true;
}

/**
 * Candidato mínimo para el rebalanceo (estructural: ProPick lo satisface).
 * Módulo puro (sin imports de runtime): importable en tests sin red.
 */
export interface RankedCandidate {
    symbol: string;
    score: number;
    strategyScore?: number | null;
    asOf?: string;
}

/**
 * Selección con tope de rotación (turnover cap) para el rebalanceo.
 *
 * Regla:
 *  1. Ordena candidatos por `strategyScore` (respaldo `score`), descendente y
 *     estable; deduplica por símbolo quedándose con el mejor rank.
 *  2. Objetivo top-20. Los incumbentes (`previousSymbols`) que sigan dentro
 *     del top-30 se mantienen (orden de rank, máx 20).
 *  3. Las huecos se rellenan con las mejores entradas nuevas, con tope de
 *     8 símbolos nuevos por rebalanceo (bootstrap con `previousSymbols`
 *     vacío: sin tope, devuelve el top-20).
 *  4. Re-estampa `asOf` (fecha del rebalanceo) en los seleccionados.
 */
export function selectRebalancedPicks<T extends RankedCandidate>(
    candidates: readonly T[],
    previousSymbols: readonly string[],
    asOf: string
): T[] {
    const previous = new Set(previousSymbols);
    const seen = new Set<string>();
    const ranked = [...candidates]
        .sort((a, b) => (b.strategyScore ?? b.score) - (a.strategyScore ?? a.score))
        .filter((c) => {
            if (seen.has(c.symbol)) return false;
            seen.add(c.symbol);
            return true;
        });
    // Incumbentes dentro del top-30 se mantienen (orden de rank, máx 20).
    const kept = ranked.slice(0, 30).filter((c) => previous.has(c.symbol)).slice(0, 20);
    const keptSymbols = new Set(kept.map((c) => c.symbol));
    // Entradas nuevas con tope de rotación.
    const freeSlots = 20 - kept.length;
    const newCap = previousSymbols.length === 0 ? freeSlots : Math.min(8, freeSlots);
    const added = ranked
        .filter((c) => !previous.has(c.symbol) && !keptSymbols.has(c.symbol))
        .slice(0, Math.max(0, newCap));
    const chosen = new Set([...kept, ...added].map((c) => c.symbol));
    return ranked.filter((c) => chosen.has(c.symbol)).map((c) => ({ ...c, asOf }));
}
