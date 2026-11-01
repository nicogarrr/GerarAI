import { cache } from 'react';

import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';

export type KeyStats = components['schemas']['KeyStats'];

/**
 * Datos clave de la ficha (estilo Stock Analysis): rango de 52 semanas,
 * próximos resultados, ex-dividendo y beta. Fuentes gratuitas que ya usa el
 * motor (cierres propios, calendario de resultados, Yahoo no oficial).
 * null = no disponible; un campo sin dato llega vacío y no se pinta.
 */
export const getKeyStats = cache(async (ticker: string): Promise<KeyStats | null> => {
  try {
    return await researchRequest<KeyStats>(`/api/companies/${encodeURIComponent(ticker)}/key-stats`, { timeoutMs: 14000 });
  } catch {
    return null;
  }
});
