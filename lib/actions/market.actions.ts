'use server';

import { researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { marketIndexUnit } from '@/lib/marketIndexUnit';

export type MarketIndex = {
  /** Timestamp aligned with the last non-null daily candle. Not a final-close guarantee. */
  priceAsOf?: number | null;
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  // F152: "index" = nivel de índice (sin unidad monetaria), "usd" = precio en dólares.
  // Normalizado en getMarketIndices vía marketIndexUnit: respuestas legacy sin
  // `unit` se resuelven por símbolo conocido; un desconocido queda ausente y el
  // front lo pinta sin sufijo monetario, nunca asumiendo USD.
  unit?: 'index' | 'usd';
};

export type MarketMover = {
  ticker: string;
  name: string;
  sector: string;
  /** ISO 4217 de la compañía; null si el backend aún no la sirve */
  currency?: string | null;
  price: number;
  /** null = sin cierre anterior registrado (cambio no medible, nunca 0 inventado) */
  change_pct: number | null;
  volume: number | null;
  date: string | null;
  /** ISO tz-aware: cuándo se registró/observó el precio de la fila (updated_at del backend) */
  registered_at?: string | null;
};

export type MarketMovers = {
  as_of: string | null;
  universe: number;
  /** Ultima sesion comun con la que se calculan los rankings. */
  session_date?: string | null;
  /** Empresas del universo sin cierre en esa sesion: fuera de los rankings. */
  excluded_not_comparable?: number;
  /** Con cambio medible pero bajo el suelo de liquidez: fuera de los rankings. */
  excluded_illiquid?: number;
  /** Suelo de liquidez aplicado (documentado en docs/features/MOVERS_LIQUIDITY_FILTER.md). */
  liquidity_floor?: { min_price: number; min_turnover: number } | null;
  /** ISO tz-aware: el registro mas reciente entre las filas del universo. */
  last_registered_at?: string | null;
  gainers: MarketMover[];
  losers: MarketMover[];
  most_active: MarketMover[];
};

/** No confundir una consulta fallida con un universo realmente vacío. */
export type MarketMoversResult = { data: MarketMovers; error: null } | { data: null; error: unknown };

export async function getMarketMoversResult(limit = 10): Promise<MarketMoversResult> {
  try {
    const payload = await cachedFetch<MarketMovers>(
      `market:movers:${limit}`,
      () => researchRequest<MarketMovers>(`/api/market/movers?limit=${limit}`),
      45,
    );
    if (!payload || !Array.isArray(payload.gainers) || !Array.isArray(payload.losers) || !Array.isArray(payload.most_active)) {
      throw new Error('Respuesta de movimientos no válida');
    }
    return { data: payload, error: null };
  } catch (error) {
    return { data: null, error };
  }
}

/** Variante legacy solo-datos. Las pantallas deben usar el resultado discriminado. */
export async function getMarketMovers(limit = 10): Promise<MarketMovers> {
  const result = await getMarketMoversResult(limit);
  return result.data ?? { as_of: null, universe: 0, gainers: [], losers: [], most_active: [] };
}
/** Resultado discriminado de índices: datos o error, nunca ambos mezclados. */
export type MarketIndicesResult = {
  data: MarketIndex[];
  /** null = la petición se completó; distinto de null = falló (red/5xx/4xx). */
  error: unknown;
};

/** Índices reales (S&P 500, Nasdaq, Bitcoin, Oro, Plata) desde el backend. */
export async function getMarketIndicesResult(): Promise<MarketIndicesResult> {
  try {
    // Caché corta en memoria (45s): el dashboard y el screener llaman a esta
    // acción en cada render; el payload es idéntico dentro de la ventana.
    const payload = await cachedFetch<{ indices: MarketIndex[] }>(
      'market:indices',
      () => researchRequest<{ indices: MarketIndex[] }>('/api/market/indices'),
      45,
    );
    // F152: normaliza la unidad en la frontera - las respuestas legacy sin
    // `unit` (caché antigua) se resuelven por símbolo conocido, no por «USD
    // por defecto» (eso volvía a pintar «US$» en el S&P 500).
    const data = (payload.indices ?? []).map((item) => ({
      ...item,
      unit: marketIndexUnit(item.symbol, item.unit) ?? undefined,
    }));
    return { data, error: null };
  } catch (error) {
    // El fallo NO se pliega a `[]` en silencio: un [] no discrimina "backend
    // caído" de "mercado sin datos" y la tarjeta terminaba infiriendo su
    // estado de la petición vecina (screener).
    console.error('getMarketIndices error:', error);
    return { data: [], error };
  }
}

/** Variante legacy solo-datos para consumidores que no discriminan el fallo. */
export async function getMarketIndices(): Promise<MarketIndex[]> {
  return (await getMarketIndicesResult()).data;
}