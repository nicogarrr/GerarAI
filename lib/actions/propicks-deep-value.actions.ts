'use server';

import { researchRequest } from '@/lib/research/client';

export interface DeepValueItem {
    ticker: string;
    name: string;
    exchange: string;
    currency: string;
    sector: string | null;
    score: number;
    price_to_book: number;
    pb_price_date: string | null;
    pb_fiscal_year: number | null;
    dividend_yield: number | null;
    yield_status: string | null;
    desacuerdo_fuentes: boolean;
    yield_extremo_revisar: boolean;
    finnhub_yield_indicated: number | null;
    fuentes: string[];
    metric_as_of: string | null;
}

export interface DeepValueResult {
    estrategia: string;
    rotulo: string;
    resultados: DeepValueItem[];
}

/**
 * Cribado deep value (P/B + yield) del backend. Estrategia SEPARADA del
 * embudo de calidad: el rotulo que llega del servidor lo dice en cada carga.
 */
export async function getDeepValue(
    pbMax: number = 1.0,
    yieldMin: number = 0,
): Promise<DeepValueResult | { error: string }> {
    try {
        return await researchRequest<DeepValueResult>(
            `/api/propicks/deep-value?pb_max=${pbMax}&yield_min=${yieldMin}&limit=50`,
            { fast: true },
        );
    } catch (error) {
        console.error('getDeepValue error:', error);
        return { error: 'No se pudo cargar el cribado deep value.' };
    }
}
