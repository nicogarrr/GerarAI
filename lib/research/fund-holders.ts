/** Fondos y ETF que tienen la acción (GET /api/ownership/funds/{ticker}, SEC Form N-PORT). */
export interface FundHolder {
  series_id: string;
  name: string;
  accession: string;
  report_date: string;
  filed: string | null;
  shares: number | null;
  value_usd: number | null;
  weight_pct: number | null;
  net_assets_usd: number | null;
  filing_url: string | null;
}

export interface FundHolders {
  // 'sin_snapshot_vinculado': la lectura es fail-closed y devuelve N/D con
  // `reason` hasta que el refresh graba un snapshot ligado al CUSIP actual.
  status: 'ok' | 'sin_datos' | 'sin_identificador' | 'sin_snapshot_vinculado';
  reason?: string;
  ticker: string;
  name: string;
  cusip: string | null;
  identity_source: string | null;
  dataset?: string;
  source?: { dataset_url: string; page: string; fetched_at: string };
  totals?: { funds: number; shares: number; value_usd: number };
  top_funds: FundHolder[];
  by_weight: FundHolder[];
  limitations: string[];
}

/** «2026q3» → «3T 2026» / «Q3 2026». */
export function datasetLabel(dataset: string | undefined, locale: string): string {
  const m = /^(\d{4})q([1-4])$/.exec(dataset ?? '');
  if (!m) return dataset ?? '—';
  return locale.startsWith('es') ? `${m[2]}T ${m[1]}` : `Q${m[2]} ${m[1]}`;
}
