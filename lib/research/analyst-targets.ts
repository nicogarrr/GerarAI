import { cache } from 'react';

import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';

export type AnalystTargets = components['schemas']['AnalystTargets'];

/**
 * Consenso de analistas (agregado Yahoo) de una empresa, deduplicado por
 * render con React `cache`: la cabecera de la ficha y el panel de vistazo
 * rápido piden lo mismo y comparten una sola llamada al motor.
 * null = no disponible (nunca un dato inventado).
 */
export const getAnalystTargets = cache(async (symbol: string): Promise<AnalystTargets | null> => {
  try {
    return await researchRequest<AnalystTargets>(`/api/companies/${encodeURIComponent(symbol)}/analyst-targets`, { timeoutMs: 14000 });
  } catch {
    return null;
  }
});
