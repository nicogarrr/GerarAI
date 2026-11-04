import { cache } from 'react';

import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';

export type AnalystHistory = components['schemas']['AnalystHistory'];
export type AnalystHistoryHorizon = components['schemas']['HorizonSummary'];
export type AnalystFirmScore = components['schemas']['FirmScore'];

/**
 * Historial de analistas (backtest de sus precios objetivo vencidos, Yahoo
 * gratuito y no oficial). null = no disponible: la tarjeta lo dice, nunca
 * inventa cifras. El motor descarga años de cierres la primera vez, de ahí
 * el plazo algo mayor que el del consenso.
 */
export const getAnalystHistory = cache(async (symbol: string): Promise<AnalystHistory | null> => {
  try {
    return await researchRequest<AnalystHistory>(`/api/companies/${encodeURIComponent(symbol)}/analyst-history`, { timeoutMs: 25000 });
  } catch {
    return null;
  }
});
