'use server';

import { researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';

/**
 * GET /api/market/regime — ultimo snapshot persistido de regimen de mercado
 * (router market_context -> market_snapshot_service.latest_snapshot).
 *
 * Regla del backend que este modulo respeta en la frontera: el payload solo
 * declara lo observado. Las metricas ausentes significan "sin datos" (lo dice
 * el propio `note` del endpoint) y las probabilidades del HMM llegan sin
 * etiqueta economica: aqui no se nombra ni se interpreta nada.
 */

/** Metrica observada por el conector (FRED): valor con fecha, unidad y fuente. */
export type RegimeObservedMetric = {
  value: number;
  /** Fecha de la observacion (YYYY-MM-DD), no la del snapshot. */
  date: string;
  /** Unidad declarada por la fuente: 'porcentaje', 'puntos porcentuales', 'indice'… */
  unit: string;
  source?: string;
  source_url?: string | null;
  fetched_at?: string;
};

/** Metrica calculada por el backend a partir de observaciones (curva 10y-2y). */
export type RegimeComputedMetric = {
  value: number;
  date: string;
  unit: string;
  /** Metodo declarado por el backend, p.ej. "DGS10 menos DGS2 en la misma fecha". */
  method?: string;
};

/** Estado del HMM: disponible con sus fechas o "sin datos" con motivo. */
export type RegimeHmm = {
  status: string;
  date?: string;
  trained_through?: string;
  training_sessions?: number;
  method?: string;
  reason?: string;
};

/** Concentracion top-10 del S&P 500 segun el snapshot de fuente (S&P DJI). */
export type RegimeTopTen = {
  status: string;
  available?: boolean;
  index?: string;
  date?: string;
  snapshot_as_of?: string;
  weight_top_ten_pct?: number;
  weight_largest_pct?: number | null;
  constituents?: number;
  source?: string;
  source_url?: string | null;
  source_tier?: string;
  synced_at?: string;
  age_days?: number;
  method?: string;
  reason?: string;
  detail?: string | null;
};

/** Bloque de estado sin valor numerico (beta de cartera: no disponible). */
export type RegimeStatusBlock = {
  status: string;
  reason?: string;
};

export type RegimeMetrics = {
  mortgage_30y_us?: RegimeObservedMetric;
  treasury_10y_us?: RegimeObservedMetric;
  treasury_2y_us?: RegimeObservedMetric;
  breakeven_10y_us?: RegimeObservedMetric;
  high_yield_spread_us?: RegimeObservedMetric;
  vix_us?: RegimeObservedMetric;
  yield_curve_10y_2y_us?: RegimeComputedMetric;
  hmm?: RegimeHmm;
  top_ten_sp500?: RegimeTopTen;
  portfolio_beta?: RegimeStatusBlock;
};

export type MarketRegime = {
  /** 'disponible' | 'obsoleto' | 'sin datos' (lo decide el backend por fecha). */
  status: string;
  coverage: string;
  /** Fecha del snapshot (YYYY-MM-DD); ausente si nunca hubo snapshot. */
  date?: string;
  generated_at?: string;
  model_version?: string;
  metrics: RegimeMetrics;
  /** Probabilidades filtradas del HMM, sin etiqueta economica (state_0/state_1). */
  probabilities: Record<string, number>;
  portfolio_beta?: RegimeStatusBlock;
  note?: string;
};

/** Resultado discriminado: datos o error, nunca ambos mezclados. */
export type MarketRegimeResult = {
  data: MarketRegime | null;
  /** null = la peticion se completo; distinto de null = fallo (red/5xx/4xx). */
  error: unknown;
};

export async function getMarketRegimeResult(): Promise<MarketRegimeResult> {
  try {
    const payload = await cachedFetch<MarketRegime>(
      'market:regime',
      () => researchRequest<MarketRegime>('/api/market/regime'),
      300,
    );
    if (!payload || typeof payload !== 'object') {
      return { data: null, error: new Error('Respuesta de régimen vacía') };
    }
    return { data: payload, error: null };
  } catch (error) {
    // No se pliega a un snapshot vacio: un "sin datos" inventado confundiria
    // "backend caido" con "aun no hay snapshots" (estados distintos).
    console.error('getMarketRegime error:', error);
    return { data: null, error };
  }
}
