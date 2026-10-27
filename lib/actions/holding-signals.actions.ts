'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { mapDcaSignals, mapFairValues, type HoldingSignals } from '@/lib/portfolio/holding-signals';

/** Nivel DCA + valor justo único de un grupo de posiciones, en dos peticiones.
 *  Cada mitad degrada por separado: sin valor justo → mapa vacío; sin motor
 *  DCA (endpoint aún no desplegado) o caído → dca=null («sin nivel»). */
export async function getHoldingSignals(symbols: string[]): Promise<HoldingSignals> {
    await requireAuthenticatedUser();
    const wanted = Array.from(new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean))).slice(0, 60);
    if (wanted.length === 0) return { fairValues: {}, dca: null };
    const [fair, dca] = await Promise.allSettled([
        researchRequest<unknown>(`/api/valuation/fair-value?tickers=${encodeURIComponent(wanted.join(','))}`, {
            cache: 'no-store',
        }),
        researchRequest<unknown>('/api/watchlist/dca-signals', { cache: 'no-store' }),
    ]);
    return {
        fairValues: fair.status === 'fulfilled' ? mapFairValues(fair.value) : {},
        dca: dca.status === 'fulfilled' ? mapDcaSignals(dca.value) : null,
    };
}
