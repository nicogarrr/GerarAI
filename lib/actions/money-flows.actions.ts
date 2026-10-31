'use server';

import { researchRequest } from '@/lib/research/client';
import { BACKEND_PAGE_SIZE, fetchAllBackendPages, type PaginatedBackendResponse } from '@/lib/paginated-backend';
import type { MoneyFlow, MoneyFlowThemeSummary } from '@/lib/market/flows';

/**
 * Flujos de dinero por tema. Como en market-themes.actions: sin catch en el
 * detalle (la página decide el estado); la lista de temas con flujo degrada a
 * vacío para que /temas se pinte igualmente si el endpoint no existe aún.
 */
export async function getMoneyFlowThemes(): Promise<MoneyFlowThemeSummary[]> {
  try {
    const payload = await researchRequest<MoneyFlowThemeSummary[]>('/api/market/flows/themes', { fast: true });
    return Array.isArray(payload) ? payload : [];
  } catch {
    return [];
  }
}

export async function getMoneyFlow(themeId: string): Promise<MoneyFlow | null> {
  try {
    const payload = await researchRequest<MoneyFlow>(
      `/api/market/flows/themes/${encodeURIComponent(themeId)}`,
      { timeoutMs: 60_000 },
    );
    if (!payload || !Array.isArray(payload.spenders)) return null;
    return payload;
  } catch {
    return null;
  }
}

/**
 * Solape con lo que el usuario ya tiene (cartera y seguimiento), para la
 * sección «Tu exposición» del flujo. Degrada a "no disponible" en silencio:
 * la sección se oculta, nunca muestra un "no tienes nada" inventado (F386).
 * Mismo patrón que #1937 (theme-holdings); se duplica aquí para no depender
 * de una PR abierta.
 */
export async function getFlowHoldings(): Promise<{
  portfolio: Set<string>;
  watchlist: Set<string>;
  unavailable: boolean;
}> {
  try {
    const [rawPositions, rawWatchlist] = await Promise.all([
      // Lectura completa: paginado page/page_size hasta agotar (fetchAllBackendPages lanza si no avanza).
      fetchAllBackendPages((page) => researchRequest<PaginatedBackendResponse<{ ticker: string }>>(`/api/portfolio/positions?page=${page}&page_size=${BACKEND_PAGE_SIZE}`, { fast: true }), (position) => position.ticker),
      researchRequest<Array<{ symbol: string }> | { items: Array<{ symbol: string }> }>('/api/watchlist', { fast: true }),
    ]);
    const positions = rawPositions;
    const watchlist = Array.isArray(rawWatchlist) ? rawWatchlist : (rawWatchlist as { items?: Array<{ symbol: string }> })?.items;
    if (!Array.isArray(positions) || !Array.isArray(watchlist)) {
      return { portfolio: new Set(), watchlist: new Set(), unavailable: true };
    }
    return {
      portfolio: new Set(positions.map((position) => position.ticker?.toUpperCase()).filter(Boolean)),
      watchlist: new Set(watchlist.map((item) => item.symbol?.toUpperCase()).filter(Boolean)),
      unavailable: false,
    };
  } catch {
    return { portfolio: new Set(), watchlist: new Set(), unavailable: true };
  }
}
