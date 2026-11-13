/**
 * Reparto de la aportación mensual ponderado por nivel DCA al cuadrado
 * (GET /api/plan/contribution-split, data-engine/app/services/plan_contribution_split.py).
 * Funciones puras para la tarjeta del plan; sin Next.
 */

export type ContributionAllocation = {
  ticker: string;
  amount: number;
  share_pct: number;
  base_weight: number;
  dca_level: number | null;
  dca_label: string | null;
  dca_period?: string | null;
  dca_status?: string | null;
  /** Nivel de hace más de un mes: no se usa (pesa 1X). */
  dca_stale?: boolean;
  multiplier: number;
  /** Ya pesa más del doble de su peso base en el plan: este mes no recibe aportación. */
  concentration_capped?: boolean;
  /** Peso actual en la cartera del plan y peso base, en %; null si no hay valores fiables. */
  market_share_pct?: number | null;
  base_share_pct?: number | null;
  /** 2X–4X en un valor poco volátil (vol < 25 %): pesa como 1X. */
  low_volatility?: boolean;
  /** Volatilidad anualizada del motor DCA, en %; null si no se conoce. */
  volatility_pct?: number | null;
  reason: string;
};

export type ContributionSplit = {
  plan_exists: boolean;
  status?: 'ok' | 'all_trim' | 'no_candidates';
  amount?: number;
  currency?: string | null;
  basis?: 'objetivos_ticker' | 'posiciones_iguales';
  dca_available?: boolean;
  summary?: string | null;
  notes?: string[];
  allocations?: ContributionAllocation[];
  unallocated?: number;
};

export function isContributionSplit(value: unknown): value is ContributionSplit {
  return typeof value === 'object' && value !== null && typeof (value as { plan_exists?: unknown }).plan_exists === 'boolean';
}

/** Clase de color del nivel: compra fuerte resaltada, recorte en ámbar, sin nivel en gris. */
export function levelTone(level: number | null): string {
  if (level == null) return 'text-gray-500';
  if (level <= 0) return 'text-amber-300';
  if (level >= 3) return 'text-teal-300';
  return 'text-gray-200';
}
