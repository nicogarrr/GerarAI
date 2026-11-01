'use server';

import { researchRequest } from '@/lib/research/client';
import { AppError } from '@/lib/types/errors';

import type { InvestorVideo } from '@/lib/ui/youtube-video';

import type { ManagerChanges, OwnershipProvenance } from './ownership.actions';
import { backendMessageForRequest } from '@/lib/research/backend-error-locale';

export type InvestorSummary = {
  slug: string;
  name: string;
  firm: string;
  kind: 'person' | 'firm' | 'company';
  cik: string | null;
  has_13f: boolean;
  /** Sin 13F pero con ficha pública (cifras con fuente y fecha). */
  has_public_profile?: boolean;
  /** 'partial' si el total guardado no cuadra con el declarado en el 13F; null sin datos. */
  coverage?: string | null;
  official_name: string | null;
  report_date: string | null;
  positions: number | null;
  value_usd_thousands: number | null;
  note: string | null;
};

export type InvestorHolding = {
  name_of_issuer: string;
  title_of_class: string;
  cusip: string;
  shares: number | null;
  value_usd_thousands: number | null;
  weight_pct: number | null;
  put_call: string | null;
  filing_url: string;
};

export type PublicFact = {
  label: string;
  value: string;
  as_of: string;
  source_url: string;
  kind: 'oficial' | 'inferido' | 'prensa';
};

/** Ficha pública de gestores sin 13F: solo lo que publican ellos o un regulador, con fuente y fecha. */
export type PublicProfile = {
  vehicle: {
    name: string;
    type: string;
    regulator_id: string;
    manager_company: string;
    start_date: string;
    source_url: string;
  };
  facts: PublicFact[];
  letters: { title: string; date: string; url: string }[];
  meetings: { title: string; year: string; url: string }[];
  holdings: unknown[] | null;
  holdings_note: string;
  /** Pie de fuentes calculado por el backend según el origen real de cada hecho. */
  provenance_note: string;
  links: { label: string; url: string }[];
};

export type InvestorDetail = InvestorSummary & {
  /** RSS server-side: ausente o vacío si no hay canal confirmado. */
  videos?: InvestorVideo[];
  public_profile?: PublicProfile | null;
  holdings: InvestorHolding[];
  limitations: string[];
  provenance?: OwnershipProvenance;
  changes?: ManagerChanges;
};

async function requestJson<T>(path: string): Promise<T> {
  // Preserva HTTP/identidad y aplica el mismo límite de lectura que el resto de research.
  return researchRequest<T>(path, { fast: true });
}

export type SyncPortfoliosResult = { success: true } | { success: false; message: string };

/** Encola la descarga de carteras 13F de este tenant y responde de inmediato (202). */
export async function syncInvestorPortfoliosNow(): Promise<SyncPortfoliosResult> {
    try {
        await researchRequest('/api/ownership/managers/sync-async', { method: 'POST' });
        return { success: true };
    } catch (error) {
        console.error('syncInvestorPortfoliosNow error:', error);
        return { success: false, message: error instanceof AppError ? await backendMessageForRequest(error.message) : 'No se pudo encolar la sincronización.' };
    }
}

export async function getInvestors(): Promise<{ investors: InvestorSummary[]; limitations: string[] }> {
  return requestJson<{ investors: InvestorSummary[]; limitations: string[] }>('/api/investors');
}

/** Ficha de un inversor; `null` si el slug no existe (la página responde 404). */
export async function getInvestor(slug: string): Promise<InvestorDetail | null> {
  try {
    return await requestJson<InvestorDetail>(`/api/investors/${encodeURIComponent(slug)}`);
  } catch (error) {
    if (error instanceof AppError && error.code === 'RESEARCH_API_ERROR' && error.statusCode === 404) return null;
    throw error;
  }
}

export type MostBoughtItem = {
  name_of_issuer: string;
  cusip: string;
  buyers_count: number;
  new_count: number;
  sellers_count: number;
  value_usd: number | null;
  buyers: { slug: string; name: string; change: 'new' | 'increased'; report_date?: string }[];
};

export type MostBought = {
  status: 'ok' | 'sin_datos';
  managers_compared: number;
  managers_without_history: number;
  managers_partial?: number;
  report_dates: string[];
  items: MostBoughtItem[];
  limitations: string[];
};

export async function getMostBought(): Promise<MostBought> {
  return requestJson<MostBought>('/api/investors/most-bought');
}

export type PortfolioOverlap = {
  status: 'ok' | 'sin_datos';
  kind: 'derivado';
  message: string | null;
  unresolved_positions: number;
  managers_with_data: number;
  managers_without_data: number;
  managers_partial: number;
  comparison_complete?: boolean;
  report_dates: string[];
  positions: {
    ticker: string; name: string; cusip: string | null; identity_source: string | null;
    status: 'sin_identificador' | 'sin_coincidencias' | 'coincidencia';
    holders: { slug: string; name: string; report_date: string; filing_date: string | null; filing_url: string | null; coverage: string | null; verification?: string | null }[];
  }[];
  not_owned: MostBoughtItem[];
};

export async function getPortfolioOverlap(): Promise<PortfolioOverlap> {
  return requestJson<PortfolioOverlap>('/api/investors/portfolio-overlap');
}

export type CompanyHolder = {
  slug: string;
  name: string;
  report_date: string | null;
  filing_date: string | null;
  filing_url: string | null;
  coverage: string | null;
  value_usd: number | null;
  shares: number | null;
};

export type CompanyHolders = {
  status: 'ok' | 'sin_datos' | 'sin_identificador';
  ticker: string;
  name: string;
  cusip: string | null;
  identity_source: string | null;
  holders: CompanyHolder[];
  managers_with_data: number;
  managers_without_data: number;
  managers_partial: number;
  limitations: string[];
};

/** Vista inversa del 13F: gestores revisados que declaran la empresa. `null` si el ticker no existe. */
export async function getCompanyHolders(ticker: string): Promise<CompanyHolders | null> {
  try {
    return await requestJson<CompanyHolders>(`/api/investors/holders/${encodeURIComponent(ticker)}`);
  } catch (error) {
    if (error instanceof AppError && error.code === 'RESEARCH_API_ERROR' && error.statusCode === 404) return null;
    throw error;
  }
}

export type InvestorDatum = {
  value: number | null;
  label: "OFICIAL" | "INFERIDO" | "SIN_DATOS";
  as_of: string | null;
  source_url: string | null;
};

export type InvestorPortfolio = {
  slug: string;
  name: string;
  firm: string;
  has_13f: boolean;
  status: "ok" | "sin_datos";
  coverage?: string;
  as_of: string | null;
  total_value_usd: InvestorDatum;
  limitations: string | string[];
  note: string | null;
  positions: {
    issuer: string;
    ticker: string | null;
    cusip: string | null;
    title_of_class: string;
    shares: InvestorDatum;
    ownership_pct: InvestorDatum;
    value_usd: InvestorDatum;
    weight_pct: InvestorDatum;
    source_form: string;
    note: string | null;
  }[];
  movements: {
    date: string | null;
    issuer: string;
    action: string;
    shares: InvestorDatum;
    price_usd: InvestorDatum;
    shares_after: InvestorDatum;
    source_form: string;
    note: string | null;
  }[];
};

export async function getInvestorPortfolio(
  slug: string,
): Promise<InvestorPortfolio> {
  return requestJson<InvestorPortfolio>(`/api/investors/${encodeURIComponent(slug)}/portfolio`);
}
