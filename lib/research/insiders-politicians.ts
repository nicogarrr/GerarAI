/**
 * Insiders (Form 4/5) y políticos (PTR de la Cámara): tipos de las rutas
 * /api/insider/summary y /api/politicians*. Todas las cifras vienen del
 * backend (deterministas); aquí solo se formatean.
 */

export type InsiderNature =
  | 'compra_mercado'
  | 'venta_mercado'
  | 'ejercicio'
  | 'concesion'
  | 'retencion_fiscal'
  | 'regalo'
  | 'otra';

export interface InsiderSide {
  trades: number;
  insiders: number;
  shares: number;
  value: number;
  value_missing: number;
  planned_10b5_1: number;
}

export interface InsiderWindow {
  days: number;
  buys: InsiderSide;
  sells: InsiderSide;
  net_value: number;
  excluded: Partial<Record<InsiderNature, number>>;
  covered: boolean;
}

export interface InsiderRow {
  insider: string | null;
  role: string | null;
  form: string;
  code: string | null;
  nature: InsiderNature;
  is_derivative: boolean;
  rule_10b5_1: boolean;
  shares: number | null;
  price: number | null;
  value: number | null;
  holdings_after: number | null;
  ownership: 'D' | 'I' | null;
  pct_of_holdings: number | null;
  tx_date: string | null;
  filing_date: string | null;
  days_late: number | null;
  late: boolean | null;
  accession_number: string;
  source_url: string | null;
}

export interface InsiderCluster {
  start: string;
  end: string;
  insiders: number;
  names: string[];
  trades: number;
  value: number;
}

export interface InsiderFirstBuy {
  kind: 'desde_compra_previa' | 'sin_compra_previa_en_datos';
  years: number | null;
  insider: string | null;
  role: string | null;
  tx_date: string | null;
  value: number | null;
  source_url: string | null;
  previous_buy: string | null;
}

export interface InsiderSummary {
  ticker: string;
  as_of: string;
  status: 'ok' | 'sin_datos';
  source: string;
  coverage: { first_filing: string | null; last_filing: string | null; filings: number; transactions: number; with_holdings_after: number } | null;
  windows: InsiderWindow[];
  clusters: InsiderCluster[];
  first_buys: InsiderFirstBuy[];
  late: { filings: number; late: number };
  transactions: InsiderRow[];
  transactions_total?: number;
}

export interface PoliticianTopTicker {
  ticker: string;
  trades: number;
}

export interface PoliticianCard {
  member_key: string;
  member: string | null;
  chamber: 'house' | 'senate' | 'executive';
  state: string | null;
  district: string | null;
  state_district: string | null;
  party: 'D' | 'R' | 'I' | null;
  bioguide: string | null;
  filings: number;
  scanned_filings: number;
  trades: number;
  tickers: number;
  top_tickers: PoliticianTopTicker[];
  last_trade: string | null;
  last_filing: string | null;
  late: number;
  late_over_30: number;
  on_time_pct: number | null;
  volume_min: number;
  volume_max: number | null;
  volume_unknown_trades?: number;
  unparsed_blocks?: number;
}

export interface PoliticiansList {
  source: string;
  chambers: Record<'house' | 'senate' | 'executive', string>;
  coverage: { years: number[]; filings: number; scanned_filings: number };
  rules: { stock_act_due_days: number; late_over_days: number };
  total: number;
  politicians: PoliticianCard[];
}

export interface PoliticianTrade {
  owner: string;
  asset: string;
  asset_type: string;
  ticker: string | null;
  type: string;
  type_label: 'compra' | 'venta' | 'venta_parcial' | 'canje' | 'otra';
  tx_date: string | null;
  notification_date: string | null;
  amount_text: string;
  amount_min: number | null;
  amount_max: number | null;
  days_late: number | null;
  member: string | null;
  member_key: string;
  party: 'D' | 'R' | 'I' | null;
  state_district: string | null;
  filing_date: string | null;
  doc_id: string;
  source_url: string | null;
}

export interface PoliticianTickerTrades {
  ticker: string;
  source: string;
  status: 'ok' | 'sin_datos';
  trades_total: number;
  buys: number;
  sells: number;
  members: { member_key: string; member: string | null; party: string | null; state_district: string | null; buys: number; sells: number; last_trade: string | null }[];
  trades: PoliticianTrade[];
}

/** Rango declarado («1.001–15.000 $»): la ley pide el rango, no la cifra. */
export function amountRange(min: number | null, max: number | null, locale: string): string {
  // useGrouping 'always': es-ES no agrupa 4 cifras («1001») y el rango se lee mal junto a «15.000».
  const fmt = (n: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 0, useGrouping: 'always' }).format(n);
  if (min === null) return '—';
  if (max === null) return `> ${fmt(min - 1)} $`;
  return `${fmt(min)}–${fmt(max)} $`;
}

export function compactUsd(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function partyTone(party: string | null): string {
  if (party === 'D') return 'border-sky-800 text-sky-300';
  if (party === 'R') return 'border-red-900 text-red-300';
  return 'border-gray-700 text-gray-300';
}
