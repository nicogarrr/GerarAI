import { cache } from 'react';
import { convertWithPortfolioFx } from '@/lib/analyst-target-currency';

import { researchRequest } from '@/lib/research/client';
import type { DcaWatchCardData } from '@/lib/dca/types';
import type { SotpResponse } from '@/lib/research/sotp';
import type { KeyStats } from '@/lib/research/key-stats';
import type { PublicShorts } from '@/lib/actions/public-shorts.actions';

/**
 * «Informe» tipo analista de la ficha (data-engine
 * app/services/analyst_report.py para mercado y cifras reales; el resto sale
 * de APIs que ya existen: tarjeta DCA, valor justo, tesis publicada y
 * desglose por partes). Aquí solo tipos y helpers puros para pintarlo.
 */
export type ReportCell = { value: number | null; unit: string; source: string; reported: boolean; basis: string; derived_q4: boolean; url?: string | null } | null;
export type ReportPeriod = { period_end: string; fiscal_quarter: string; revenue: ReportCell; ebitda: ReportCell };
export type ReportPoint = { value: number | null; unit: string | null; period_end: string | null; provenance: string } | null;

export type AnalystReportData = {
  ticker: string;
  company: string;
  version: string;
  market: {
    price: number | null;
    price_date: string | null;
    currency: string | null;
    avg_volume: number | null;
    avg_volume_sessions: number;
    shares_outstanding: ReportPoint;
    shares_diluted: ReportPoint;
    market_cap: number | null;
    market_cap_currency?: string | null;
    enterprise_value_currency?: string | null;
    market_cap_basis: 'shares_outstanding' | 'shares_diluted' | null;
    cash: ReportPoint;
    total_debt: ReportPoint;
    enterprise_value: number | null;
    enterprise_value_reason: string | null;
  };
  estimates: { annual: ReportPeriod[]; quarterly: ReportPeriod[] };
};

/** Tesis publicada tal y como la trae /api/thesis/{t}/versions (solo lo que pinta el informe). */
export type ReportThesis = {
  id?: number;
  version: number;
  status: string;
  created_at?: string | null;
  executive_summary?: string | null;
  hypothesis?: string | null;
  catalysts?: { label?: string | null; date?: string | null }[] | null;
  invalidation_criteria?: string[] | null;
  narrative_sections?: { titulo: string; parrafos: string[] }[] | null;
  thesis_markdown?: string | null;
  bear_value?: number | string | null;
  base_value?: number | string | null;
  bull_value?: number | string | null;
};

/** Valor justo resumido (lib/research/valuation-summary.ts) y líneas de honestidad del motor. */
export type ReportFairValue = {
  value: number | null;
  currency: string | null;
  label: string;
  as_of: string | null;
  publishable: boolean;
  reason?: string | null;
};

export type ReportHonesty = {
  trackRecord: string | null;
  sbc: string | null;
  baseRate: string | null;
  impliedGrowth: string | null;
};

export type ReportInputs = {
  ticker: string;
  report: AnalystReportData | null;
  card: DcaWatchCardData | null;
  fair: ReportFairValue | null;
  thesis: ReportThesis | null;
  sotp: SotpResponse | null;
  honesty: ReportHonesty;
  engineRange: { low: number; high: number; currency?: string | null } | null;
  keyStats: KeyStats | null;
  shorts: PublicShorts | null;
  /** Consenso propio de GerarAI (data-engine app/services/own_consensus.py); null si falla la lectura. */
  consensus?: OwnConsensusData | null;
  /** Fecha de hoy (YYYY-MM-DD) en la que se compone el informe. */
  today: string;
};

/** Una celda de ``GET /api/companies/{t}/own-consensus`` (solo lo que pinta el informe). */
export type OwnConsensusCell = {
  metric: string;
  period: string;
  period_end: string;
  status: string;
  source?: string | null;
  low?: number | null;
  mid?: number | null;
  high?: number | null;
  formula?: string | null;
  reason?: string | null;
  citations?: { kind?: string; url?: string | null; date?: string | null }[] | null;
  confidence?: { level?: string | null; reason?: string | null } | null;
};
export type OwnConsensusData = { version?: string; as_of?: string; cells: OwnConsensusCell[] };

export const CONSENSUS_METRICS = ['revenue', 'operating_income', 'eps'] as const;
export type ConsensusRow = { period: string; period_end: string; isYear: boolean; cells: Record<(typeof CONSENSUS_METRICS)[number], OwnConsensusCell | null> };

/** Filas del consenso propio por periodo (los trimestres y años que aún no se han presentado), en orden. */
export function consensusRows(data: OwnConsensusData | null | undefined): ConsensusRow[] {
  const rows = new Map<string, ConsensusRow>();
  for (const cell of data?.cells ?? []) {
    if (!(CONSENSUS_METRICS as readonly string[]).includes(cell.metric) || cell.status === 'vencido') continue;
    const row = rows.get(cell.period) ?? { period: cell.period, period_end: cell.period_end, isYear: cell.period.startsWith('fy'), cells: { revenue: null, operating_income: null, eps: null } };
    row.cells[cell.metric as (typeof CONSENSUS_METRICS)[number]] = cell;
    rows.set(cell.period, row);
  }
  return [...rows.values()]
    .filter((row) => Object.values(row.cells).some((c) => c && c.status === 'estimado'))
    .sort((a, b) => (a.period_end === b.period_end ? Number(a.isYear) - Number(b.isYear) : a.period_end.localeCompare(b.period_end)));
}

/** Primer enlace citado de una celda (filing, guía o nota de prensa), si lo hay. */
export function consensusSourceUrl(cell: OwnConsensusCell | null): string | null {
  const url = cell?.citations?.find((c) => typeof c?.url === 'string' && /^https?:\/\//.test(c.url))?.url;
  return url ?? null;
}

export async function getOwnConsensus(ticker: string): Promise<OwnConsensusData | null> {
  try {
    return await researchRequest<OwnConsensusData>(`/api/companies/${encodeURIComponent(ticker)}/own-consensus`, { timeoutMs: 12000 });
  } catch {
    return null;
  }
}

export const getAnalystReport = cache(async (ticker: string): Promise<AnalystReportData | null> => {
  try {
    return await researchRequest<AnalystReportData>(`/api/companies/${encodeURIComponent(ticker)}/analyst-report`, { timeoutMs: 15000 });
  } catch {
    return null;
  }
});

/** Última versión publicada de la tesis (null si no hay o falla la lectura). */
export async function getPublishedThesis(ticker: string): Promise<ReportThesis | null> {
  try {
    const versions = await researchRequest<ReportThesis[]>(`/api/thesis/${encodeURIComponent(ticker)}/versions`, { timeoutMs: 12000 });
    return versions.filter((v) => v.status === 'published').sort((a, b) => b.version - a.version)[0] ?? null;
  } catch {
    return null;
  }
}

function finite(value: unknown): number | null {
  const n = typeof value === 'string' ? Number(value) : value;
  return typeof n === 'number' && Number.isFinite(n) ? n : null;
}

/**
 * Rango de valor justo de la cabecera: el de la tesis publicada (bajista–alcista)
 * cuando el valor justo sale de la tesis; si no, el del motor. Nunca una recomendación.
 */
export function fairValueRange(fair: ReportFairValue | null, thesis: ReportThesis | null, engine: { low: number; high: number } | null): { low: number; high: number; source: 'thesis' | 'engine' } | null {
  const fromThesis = (fair?.label ?? '').toLowerCase().includes('tesis') || (fair?.label ?? '').toLowerCase().includes('thesis');
  if (thesis && (fromThesis || !engine)) {
    const low = finite(thesis.bear_value);
    const high = finite(thesis.bull_value);
    if (low !== null && high !== null && high >= low) return { low, high, source: 'thesis' };
  }
  if (engine && Number.isFinite(engine.low) && Number.isFinite(engine.high) && engine.high >= engine.low) return { ...engine, source: 'engine' };
  return null;
}

/** Rango del motor desde ValuationResponse.fair_value_range ({low, high} o {min, max}). */
export function engineRangeFrom(range: Record<string, unknown> | null | undefined): { low: number; high: number; currency?: string | null } | null {
  if (!range) return null;
  const low = finite(range.low ?? range.min);
  const high = finite(range.high ?? range.max);
  return low !== null && high !== null ? { low, high, ...(typeof range.currency === 'string' ? { currency: range.currency } : {}) } : null;
}

/** Riesgos: criterios de invalidación + secciones de la tesis cuyo título habla de riesgos. */
export function thesisRisks(thesis: ReportThesis | null, sections: { titulo: string; parrafos: string[] }[]): { criteria: string[]; sections: { titulo: string; parrafos: string[] }[] } {
  const criteria = (thesis?.invalidation_criteria ?? []).filter((c) => typeof c === 'string' && c.trim());
  return { criteria, sections: sections.filter((s) => /riesg|risk/i.test(s.titulo)) };
}

/** Totales de las estimaciones del usuario desde su desglose por partes (siempre suyas). */
export function userEstimates(sotp: SotpResponse | null): { year: number; revenue: number | null; ebitda: number | null; currency: string | null; author: string | null; origin: string } | null {
  const model = sotp?.model;
  const result = sotp?.result;
  if (!sotp || !model || !result) return null;
  return {
    year: model.valuation_year,
    revenue: finite(result.total_revenue),
    ebitda: finite(result.total_ebitda),
    currency: model.currency ?? null,
    author: model.author ?? null,
    origin: sotp.origin ?? 'saved',
  };
}

/** Variación del precio frente a un valor (ratio, +0,25 = 25 % por encima). */
export function vsPrice(value: number | null | undefined, price: number | null | undefined): number | null {
  if (value == null || price == null || !Number.isFinite(value) || !Number.isFinite(price) || price <= 0) return null;
  return value / price - 1;
}

/** Compare only after an exact unit conversion. No FX is invented. */
export function reportVsPrice(value: number | null | undefined, valueCurrency: string | null | undefined, price: number | null | undefined, priceCurrency: string | null | undefined): number | null {
  if (value == null || !valueCurrency || !priceCurrency) return null;
  const converted = convertWithPortfolioFx(value, valueCurrency, priceCurrency, null, null);
  return converted === null ? null : vsPrice(converted, price);
}
