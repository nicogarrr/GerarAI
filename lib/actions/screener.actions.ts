'use server';

import { cache } from 'react';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { jsonBody, researchRequest } from '@/lib/research/client';
import { formatNumber } from '@/lib/format';
import { fetchDatedChanges } from '@/lib/market/dated-change';
import type { components } from '@/lib/research/openapi.generated';
import type { EngineScreenResult, ScreenCriterion } from '@/lib/screener-types';

export type ScreenerResult = {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  changePercent: number | null;
  marketCap: number;
  pe: number;
  pb: number;
  roe: number;
  volume: number;
  beta: number;
  sector: string;
  exchange: string;
  type: string;
};

export async function exportScreenerResults(results: ScreenerResult[]): Promise<string> {
  await requireAuthenticatedUser();
  // Generate CSV
  const headers = [
    'Symbol', 'Name', 'Price', 'Change', 'Change %', 'Market Cap', 
    'P/E', 'P/B', 'ROE', 'Volume', 'Beta', 'Sector', 'Exchange', 'Type'
  ];
  
  const rows = results.map(r => [
    r.symbol,
    r.name,
    formatNumber(r.price, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    formatNumber(r.change, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    formatNumber(r.changePercent, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    formatNumber(r.marketCap, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
    formatNumber(r.pe, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    formatNumber(r.pb, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    formatNumber(r.roe, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    formatNumber(r.volume, { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
    formatNumber(r.beta, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    r.sector,
    r.exchange,
    r.type,
  ]);
  
  const csv = [
    headers.join(','),
    ...rows.map(row => row.join(','))
  ].join('\n');
  
  return csv;
}

// ============================================================================
// SCREENER REAL (GET /api/screeners/real del data-engine)
// ----------------------------------------------------------------------------
// Respaldado por el endpoint real del backend (Finnhub free tier): precios del
// día, market cap, sector y volumen REALES. Firma estándar vía researchRequest
// (lib/research/client.ts). Mismo shape que consumía el front (array en
// `screener`, mismos nombres de campo que ScreenerResult).
// ============================================================================

export type RealScreenerFilters = {
  marketCapMoreThan?: number;
  sector?: string;
  limit?: number;
};

export type RealScreenerRow = components['schemas']['ScreenerRealItemOut'];

export type RealScreenerResponse = components['schemas']['ScreenerRealOut'];

/**
 * Screener real: consulta el backend (Finnhub free) con precios y market caps
 * reales del día. Devuelve [] si no hay datos (nunca datos inventados).
 */
export const getScreenerStocksReal = cache(
  async (filters: RealScreenerFilters = {}): Promise<RealScreenerRow[]> => {
    return (await getScreenerStocksRealWithStatus(filters)).rows;
  },
);

/** Versión con estado: además de las filas devuelve `refreshing` (carga fría
 *  con refresco en vuelo, distinto de «filtro sin resultados») y el tamaño
 *  del universo seguido, para que la pantalla declare su alcance real. */
export const getScreenerStocksRealWithStatus = cache(
  async (filters: RealScreenerFilters = {}): Promise<{
    rows: RealScreenerRow[];
    refreshing: boolean;
    unavailable: boolean;
    universeSize: number | null;
  }> => {
    await requireAuthenticatedUser();
    const params = new URLSearchParams();
    if (filters.marketCapMoreThan) {
      params.set('marketCapMoreThan', String(filters.marketCapMoreThan));
    }
    if (filters.sector) {
      params.set('sector', filters.sector);
    }
    params.set('limit', String(filters.limit ?? 25));
    const qs = params.toString();
    const data = await researchRequest<RealScreenerResponse>(
      `/api/screeners/real${qs ? `?${qs}` : ''}`,
      { cache: 'no-store' },
    );
    const rows = data?.screener ?? [];
    const refreshing = data?.refreshing === true;
    // Sin filas y sin refresh en vuelo: el proveedor no tiene datos. No se
    // presenta como «filtro sin resultados».
    const unavailable = rows.length === 0 && data?.unavailable === true && !refreshing;
    const universeSize = typeof data?.universe_size === 'number' ? data.universe_size : null;
    // Precio, variación y fecha salen de los mismos cierres datados que Movers.
    const dated = await fetchDatedChanges(rows.map((row) => row.symbol));
    const mapped = rows.map((row) => {
      const d = dated[row.symbol.toUpperCase()];
      if (!d) return row;
      return {
        ...row,
        price: d.price,
        currency: d.currency,
        change: d.change,
        changePercent: d.changePercent,
        prevClose: d.previousClose,
        priceDate: d.date,
      };
    });
    return { rows: mapped, refreshing, unavailable, universeSize };
  },
);


/** Procedencia del valor justo ÚNICO (backend fair_value_service). */
export type FairValueSource = 'tesis' | 'motor' | 'motor_orientativo';

export type FairValueReading = {
  value: number;
  /** true = valoracion final (tesis publicada o motor publicable); false =
   *  orientacion del motor: el numero existe pero algun input no es trazable
   *  a fuente datada. */
  publishable: boolean;
  /** De donde sale el numero: misma precedencia en watchlist, inicio y screener. */
  source: FairValueSource;
  /** Etiqueta lista para pintar, p. ej. «Tesis publicada v3» o «Motor de valoración». */
  label: string;
  /** Fecha (ISO) de la tesis o del calculo del motor; null si no consta. */
  asOf: string | null;
};

const FAIR_VALUE_SOURCES: readonly FairValueSource[] = ['tesis', 'motor', 'motor_orientativo'];

/** Lectura del valor justo ÚNICO (backend /api/valuation/{ticker}/fair-value).
 *  Antes el inicio y el screener leian el motor y la watchlist la tesis, y el
 *  mismo ticker podia salir infravalorado en una pagina y sobrevalorado en
 *  otra. Ahora todos leen la misma cifra con la misma precedencia (tesis
 *  publicada reciente > motor publicable > tesis antigua > motor orientativo)
 *  y su etiqueta de procedencia. Un valor no publicable sigue siendo una
 *  orientacion valida si se declara (publishable=false).
 *  null solo cuando no hay ningun valor o la peticion falla. */
export const getFairValueReading = cache(
  async (symbol: string): Promise<FairValueReading | null> => {
    await requireAuthenticatedUser();
    try {
      const data = await researchRequest<{
        value?: number | null;
        source?: string | null;
        label?: string | null;
        publishable?: boolean;
        as_of?: string | null;
      }>(`/api/valuation/${encodeURIComponent(symbol)}/fair-value`, { cache: 'no-store' });
      const value = data?.value ?? null;
      const source = FAIR_VALUE_SOURCES.find((s) => s === data?.source);
      if (value == null || !(value > 0) || !source) return null;
      return {
        value,
        publishable: data?.publishable === true,
        source,
        label: data?.label || 'Valor justo',
        asOf: data?.as_of ?? null,
      };
    } catch {
      return null;
    }
  },
);

// ============================================================================
// MOTOR DE SCREENER (POST /api/screeners/run ad-hoc y /screens/{id}/run)
// ----------------------------------------------------------------------------
// El motor del backend (ScreenerService: metricas calculadas trazables,
// cobertura y confianza por empresa) es la fuente primaria. La lectura
// Finnhub/GET /api/screeners/real de arriba queda como fallback offline:
// precios del dia cuando el motor no responde, nunca como sustituto del
// analisis de cobertura.
// ============================================================================

// El contrato del motor vive en lib/screener-types.ts (compartido con
// research-tools.actions); EngineCriterion es el mismo criterio con su
// nombre histórico aquí.
export type EngineCriterion = ScreenCriterion;
export type { EngineScreenRow, EngineScreenResult } from '@/lib/screener-types';

/** POST /api/screeners/run — filtro ad-hoc contra el motor (trazable). */
export async function runScreenerEngine(
  criteria: EngineCriterion[],
  options?: { rankingFormula?: string; rankingDirection?: 'asc' | 'desc' },
): Promise<EngineScreenResult> {
  await requireAuthenticatedUser();
  if (!criteria.length) throw new Error('Define al menos un criterio para ejecutar el motor');
  return researchRequest<EngineScreenResult>('/api/screeners/run', {
    method: 'POST',
    body: jsonBody({
      criteria,
      ranking_formula: options?.rankingFormula ?? null,
      ranking_direction: options?.rankingDirection ?? 'desc',
    }),
  });
}

/** POST /api/screeners/screens/{id}/run — ejecuta un filtro guardado. */
export async function runSavedScreenerEngine(screenId: number): Promise<EngineScreenResult> {
  await requireAuthenticatedUser();
  if (!Number.isInteger(screenId) || screenId <= 0) throw new Error('Filtro no válido');
  return researchRequest<EngineScreenResult>(`/api/screeners/screens/${screenId}/run`, {
    method: 'POST',
  });
}

/** GET /api/screeners/screens — filtros guardados del motor (para la UI). */
export async function getSavedScreenerEngines(): Promise<
  Array<{ id: number; name: string; description: string; alerts_enabled: boolean; last_run_at: string | null }>
> {
  await requireAuthenticatedUser();
  return researchRequest<
    Array<{ id: number; name: string; description: string; alerts_enabled: boolean; last_run_at: string | null }>
  >('/api/screeners/screens', { cache: 'no-store' });
}
