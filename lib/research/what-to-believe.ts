import { cache } from 'react';

import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';

export type WhatToBelieve = components['schemas']['WhatToBelieve'];
export type ImpliedWacc = components['schemas']['ImpliedWacc'];

/**
 * «Qué hace falta creer»: WACC implícito al precio y al consenso, crecimiento
 * del DCF inverso y contraste con un múltiplo de salida, leídos del DCF ya
 * calculado. null = no disponible (la tarjeta lo dice, nunca inventa cifras).
 * El backend recalcula la valoración, de ahí el plazo algo mayor.
 */
export const getWhatToBelieve = cache(async (ticker: string): Promise<WhatToBelieve | null> => {
  try {
    return await researchRequest<WhatToBelieve>(`/api/valuation/${encodeURIComponent(ticker)}/what-to-believe`, { timeoutMs: 25000 });
  } catch {
    return null;
  }
});
