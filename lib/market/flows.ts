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
  destinations_note: string | null;
  suppliers_note: string | null;
};

export type MoneyFlowThemeSummary = { id: string; name: string; tagline: string };

/**
 * Clave de lista para proveedores. El mismo ticker puede aparecer varias
 * veces (RTX/LMT como proveedores duplicados): no basta ticker ni nombre;
 * el índice desempata sin ocultar el duplicado.
 */
export function flowSupplierKey(
  supplier: Pick<FlowSupplier, 'ticker' | 'name'>,
  index: number,
): string {
  const ticker = supplier.ticker?.trim().toUpperCase() || 'sin-ticker';
  return `${ticker}::${supplier.name}::${index}`;
}

/**
 * Importe de un flujo respetando la divisa de la fila (regla de Nico):
 * USD en es-ES con su símbolo → «35,7 mil M US$» (Nico 29-oct-2026: todo en
 * formato español); otras divisas en es-ES con el código explícito (nunca se
 * asume USD cuando la fila dice otra cosa).
 */
export function formatFlowAmount(value: number | null, unit = 'USD', fallback = 'N/D'): string {
  if (value === null || !Number.isFinite(value)) return fallback;
  const abs = Math.abs(value);
  const scaled = abs >= 1e9 ? value / 1e9 : abs >= 1e6 ? value / 1e6 : value;
  const suffix = abs >= 1e9 ? 'B' : abs >= 1e6 ? 'M' : '';
  const digits = abs >= 1e6 ? 1 : 0;
  if (unit === 'USD') {
    const usdSuffix = abs >= 1e9 ? ' mil M' : abs >= 1e6 ? ' M' : '';
    return `${scaled.toLocaleString('es-ES', { maximumFractionDigits: digits, useGrouping: 'always' } as Intl.NumberFormatOptions)}${usdSuffix}\u00a0US$`;
  }
  const number = scaled.toLocaleString('es-ES', { maximumFractionDigits: digits });
  return suffix ? `${number} ${suffix} ${unit}` : `${number} ${unit}`;
}
