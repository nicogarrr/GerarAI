export type AlignmentEvidence = { value: number; unit: string; date: string; filed: string; url: string; metric: string; fact_id: number };
export type AlignmentRatio = { value: number | null; sources?: AlignmentEvidence[]; reason?: string };
export type AlignmentYear = {
  year: number; shares: AlignmentEvidence | null; shares_change_pct: AlignmentRatio;
  share_basis: string | null; sbc: AlignmentEvidence | null;
  sbc_revenue_pct: AlignmentRatio; sbc_fcf_pct: AlignmentRatio;
  repurchases: AlignmentEvidence | null; repurchases_label: string; change_label: string; warnings: string[]; quality_warnings?: string[];
};
export type AlignmentTrade = { code: string; plan: boolean | null; value: number | null; reported_value?: string | null; date: string; url: string | null; accession: string; form: string };
export type AlignmentWindow = {
  months: number; from: string; to: string; status: string; reason: string;
  groups: { buys: AlignmentTrade[]; planned_sales: AlignmentTrade[]; unplanned_sales: AlignmentTrade[]; unknown_sales: AlignmentTrade[] };
  net_value: number | null; discretionary_net_value: number | null; warnings: string[];
};
export type ManagementAlignment = { status: 'ok' | 'pendiente'; ticker: string; reason?: string; stale?: boolean; computed_at?: string; as_of?: string; years?: AlignmentYear[]; insiders?: AlignmentWindow[]; dilution_reason?: string | null };

export function alignmentNumber(value: number, unit = ''): string {
  return new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value) + (unit ? ` ${unit}` : '');
}

export function alignmentUrl(value: string | null): string | null {
  try {
    if (!value) return null;
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? value : null;
  } catch { return null; }
}
