/**
 * Flujo de dinero por tema (quién gasta → a dónde va → quién cobra).
 *
 * Espejo del payload de GET /api/market/flows/themes/{id}. Regla de
 * veracidad compartida con el backend: toda cifra es "reportado" (fuente
 * oficial enlazable) o "estimacion_terceros" (atribuida); no hay tercera vía.
 */

export type FlowSource = {
  kind: 'reportado' | 'estimacion_terceros';
  label: string;
  url: string | null;
  note: string | null;
};

export type FlowSpender = {
  key: string;
  label: string;
  ticker: string | null;
  amount: number | null;
  unit: string;
  period_label: string | null;
  source: FlowSource | null;
  reason: string | null;
  note: string | null;
  extra_amount: number | null;
  extra_label: string | null;
  extra_source: FlowSource | null;
};

export type FlowDestination = {
  label: string;
  amount: number | null;
  unit: string;
  source: FlowSource;
};

export type FlowSupplier = {
  ticker: string | null;
  name: string;
  amount: number | null;
  unit: string;
  reason: string;
  note: string | null;
  source: FlowSource | null;
};

export type MoneyFlow = {
  id: string;
  name: string;
  tagline: string;
  generated_at: string;
  period_label: string | null;
  spenders: FlowSpender[];
  spenders_total: { amount: number; unit: string; note: string } | null;
  destinations: FlowDestination[];
  suppliers: FlowSupplier[];
  method: string;
  limitation: string;
  notes: string[];
};

export type MoneyFlowThemeSummary = { id: string; name: string; tagline: string };

/** 35_700_000_000 USD → «35,7 B$» (miles de millones, es-ES). */
export function formatFlowAmount(value: number | null, fallback = 'N/D'): string {
  if (value === null || !Number.isFinite(value)) return fallback;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toLocaleString('es-ES', { maximumFractionDigits: 1 })} B$`;
  if (abs >= 1e6) return `${(value / 1e6).toLocaleString('es-ES', { maximumFractionDigits: 1 })} M$`;
  return value.toLocaleString('es-ES', { maximumFractionDigits: 0 }) + ' $';
}
