'use server';

import { researchRequest } from '@/lib/research/client';
import type { HistoricalStressReport } from '@/types/historical-stress';

export async function getHistoricalStress(ticker?: string): Promise<HistoricalStressReport> {
    const params = new URLSearchParams();
    if (ticker) params.set('ticker', ticker);
    // Cliente común del engine: hereda presupuesto de lectura, deadline
    // único y retry 429. Antes era un fetch firmado a mano SIN timeout:
    // un engine colgado dejaba la página de estrés esperando indefinidamente.
    return researchRequest<HistoricalStressReport>(`/api/risk/historical-stress?${params}`);
}
