/** Institucionales de todo el 13F (GET /api/ownership/institutions/{ticker}). */
export type InstitutionalStatus = 'nuevo' | 'aumenta' | 'reduce' | 'igual' | 'vende_todo' | 'sin_13f_aun' | 'sin_13f_previo';

export interface InstitutionalHolder {
  cik: string;
  name: string;
  shares: number;
  prev_shares: number;
  change: number;
  change_pct: number | null;
  pct_of_13f: number | null;
  status: InstitutionalStatus | '';
  accession: string | null;
  filed: string | null;
  filing_url: string | null;
  prev_filing_url: string | null;
}

export interface InstitutionalHolders {
  // 'sin_snapshot_vinculado': la lectura es fail-closed y devuelve N/D con
  // `reason` hasta que el refresh graba un snapshot ligado al CUSIP actual.
  status: 'ok' | 'sin_datos' | 'sin_identificador' | 'sin_snapshot_vinculado';
  reason?: string;
  ticker: string;
  name: string;
  cusip: string | null;
  identity_source: string | null;
  period?: string;
  prior_period?: string | null;
  source?: { dataset_url: string; prior_dataset_url: string | null; fetched_at: string; page: string };
  totals?: {
    holders: number;
    holders_prior: number;
    shares: number;
    shares_prior: number;
    net_comparable: number;
    nuevo: number;
    aumenta: number;
    reduce: number;
    igual: number;
    vende_todo: number;
    sin_13f_aun: number;
    sin_13f_previo: number;
  };
  top_holders: InstitutionalHolder[];
  buyers: InstitutionalHolder[];
  sellers: InstitutionalHolder[];
  limitations: string[];
}

/** Acciones en formato compacto con signo opcional (1,2 M; +350 mil). */
export function compactShares(value: number, intl: string, signed = false): string {
  const text = new Intl.NumberFormat(intl, { notation: 'compact', maximumFractionDigits: 1 }).format(Math.abs(value));
  if (!signed) return text;
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

export function pct(value: number | null, intl: string, signed = false): string | null {
  if (value === null || !Number.isFinite(value)) return null;
  const text = new Intl.NumberFormat(intl, { maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(Math.abs(value));
  return `${signed ? (value > 0 ? '+' : value < 0 ? '−' : '') : ''}${text} %`;
}
