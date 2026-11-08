'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import type { DcaWatchCardData } from '@/lib/dca/types';
import { researchRequest } from '@/lib/research/client';

/** Tarjeta DCA de un ticker (niveles S/M/T/A, racha, riesgo, «¿por qué?»). null = no disponible. */
export async function getDcaWatchCard(symbol: string): Promise<DcaWatchCardData | null> {
    try {
        await requireAuthenticatedUser();
        return await researchRequest<DcaWatchCardData>(`/api/watchlist/dca-signals/${encodeURIComponent(symbol)}/card`, { timeoutMs: 20000 });
    } catch (error) {
        console.error('getDcaWatchCard error:', error);
        return null;
    }
}
