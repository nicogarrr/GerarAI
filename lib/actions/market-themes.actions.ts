'use server';

import { researchRequest } from '@/lib/research/client';
import type { MarketThemes } from '@/lib/market/themes';

/**
 * Temas de mercado (cestas curadas, media simple, YTD y 1M).
 *
 * Sin catch a propósito: si el servidor no responde, la página muestra el estado
 * "desconectado" en vez de un ranking vacío que parezca un dato. El backend ya cachea
 * una hora; la primera petición en frío puede tardar, de ahí el presupuesto de 60 s.
 */
export async function getMarketThemes(): Promise<MarketThemes> {
  const payload = await researchRequest<MarketThemes>('/api/market/themes', { timeoutMs: 60_000 });
  if (!payload || !Array.isArray(payload.themes)) {
    throw new Error('Respuesta de temas de mercado no válida.');
  }
  return payload;
}

