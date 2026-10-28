'use server';

import { researchRequest } from '@/lib/research/client';

export interface RadarCandidate {
    symbol: string;
    name: string | null;
    exchange: string | null;
    currency: string | null;
    price_to_book: number | null;
    dividend_yield: number | null;
    yield_extremo_revisar: boolean;
    fuente: string;
    en_universo_propio: boolean;
    via_cotejo: string | null;
}

export interface RadarResult {
    rotulo: string;
    generado_en: string;
    regiones: string[];
    candidatos: RadarCandidate[];
}

/** Radar global Yahoo (fuente no oficial): solo propone candidatos. */
export async function getRadarCandidates(regions: string[]): Promise<RadarResult> {
    const params = new URLSearchParams();
    if (regions.length > 0) params.set('regions', regions.join(','));
    const query = params.toString();
    return researchRequest<RadarResult>(
        `/api/propicks/deep-value/radar${query ? `?${query}` : ''}`,
        { fast: true },
    );
}
