// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { naFor } from '../format.ts';

export type ParticipationFiling = {
  accession_number: string;
  form: string;
  holder_name: string | null;
  aggregate_shares: number | null;
  percent_of_class: number | null;
  snapshot_date: string | null;
  filing_date: string | null;
  source_url: string | null;
  status: string;
};
export type ParticipationResponse = { ticker: string; count: number; filings: ParticipationFiling[] };
export const participationNumber = (value: number | null, percent = false, locale: 'es' | 'en' = 'es'): string =>
  value === null || !Number.isFinite(value) ? naFor(locale) :
    new Intl.NumberFormat(locale === 'en' ? 'en-US' : 'es-ES', { maximumFractionDigits: percent ? 4 : 0, useGrouping: true }).format(value) + (percent ? (locale === 'en' ? '%' : ' %') : '');
export function participationSource(url: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && ['www.sec.gov', 'sec.gov'].includes(parsed.hostname)
      && parsed.pathname.startsWith('/Archives/edgar/data/') ? url : null;
  } catch { return null; }
}
