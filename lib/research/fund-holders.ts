/** Fondos y ETF que tienen la acción (GET /api/ownership/funds/{ticker}, SEC Form N-PORT). */
import type { Locale } from '@/lib/i18n/locale';
// Import relativo con atributo, igual que ownership-display.ts: estos textos
// fijos del backend viven en los diccionarios y aquí solo se cruzan.
import esResearch from '../i18n/messages/es/research.json' with { type: 'json' };
import enResearch from '../i18n/messages/en/research.json' with { type: 'json' };

const BACKEND_TEXT_KEYS = ['nportIncomplete', 'nportSnapshotLegacy', 'nportLimitUniverse', 'nportLimitDates', 'nportLimitWeight'] as const;
// Uso por literal para el guard de i18n (claves consumidas por iteración).
export const FUND_HOLDERS_BACKEND_TEXT_KEY_LITERALS = [
    'research.fondos.backendText.nportIncomplete',
    'research.fondos.backendText.nportSnapshotLegacy',
    'research.fondos.backendText.nportLimitUniverse',
    'research.fondos.backendText.nportLimitDates',
    'research.fondos.backendText.nportLimitWeight',
] as const;

const backendText = (area: typeof esResearch, key: string): string =>
    (area.fondos.backendText as Record<string, string>)[key];

/** Aviso de calidad N-PORT del backend (castellano) -> inglés. */
const NOTICE_EN: Record<string, string> = Object.fromEntries(
    BACKEND_TEXT_KEYS.map((key) => [backendText(esResearch, key), backendText(enResearch, key)]),
);

// Las tres limitaciones base ya las resume el pie (research.fondos.limits):
// no se repiten; solo se pintan los avisos de calidad adicionales.
const BASE_LIMITATIONS = new Set(BACKEND_TEXT_KEYS.slice(2).map((key) => backendText(esResearch, key)));

/** Traduce un aviso N-PORT sin ocultar textos nuevos del backend. */
export function fundHoldersNotice(text: string, locale: Locale): string {
    return locale === 'en' ? NOTICE_EN[text] ?? text : text;
}

/** Avisos de limitations que no cubre el pie fijo del panel. */
export function fundHoldersExtraNotices(limitations: string[] | undefined): string[] {
    return (limitations ?? []).filter((text) => !BASE_LIMITATIONS.has(text));
}

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
  totals?: { funds: number; shares: number; value_usd: number | null };
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
