'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import type { EventMaterials } from '@/lib/earnings-materials';
import { researchRequest } from '@/lib/research/client';

/**
 * Material oficial (SEC) de resultados ya publicados, resuelto en el backend. Nunca lanza: un
 * fallo devuelve mapa vacio y el calendario se pinta igual. Clave: `TICKER|YYYY-MM-DD`.
 */
export async function getEarningsMaterials(): Promise<Record<string, EventMaterials>> {
    await requireAuthenticatedUser();
    try {
        const response = await researchRequest<{ items: Record<string, EventMaterials> }>('/api/calendar/followed/materials');
        return response.items ?? {};
    } catch {
        return {};
    }
}
