/**
 * Reparto de la aportación mensual ponderado por nivel DCA
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

export function formatSplitAmount(value: number, currency: string | null | undefined): string {
  const text = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: 'always' }).format(value);
  return currency ? `${text} ${currency}` : text;
}

export const BASIS_LABELS: Record<string, string> = {
  objetivos_ticker: 'Pesos objetivo por ticker × nivel DCA',
  posiciones_iguales: 'Posiciones vivas a partes iguales × nivel DCA',
};

/** Texto vacío honesto según el estado; null cuando hay reparto que mostrar. */
export function splitEmptyMessage(split: ContributionSplit | null): string | null {
  if (!split || !split.plan_exists) return 'Configura el plan para ver el reparto de la aportación.';
  if (split.status === 'no_candidates') {
    return 'El plan no tiene objetivos por ticker ni posiciones vivas: no hay a qué repartir la aportación.';
  }
  return null;
}

/** Clase de color del nivel: compra fuerte resaltada, recorte en ámbar, sin nivel en gris. */
export function levelTone(level: number | null): string {
  if (level == null) return 'text-gray-500';
  if (level <= 0) return 'text-amber-300';
  if (level >= 3) return 'text-teal-300';
  return 'text-gray-200';
}
