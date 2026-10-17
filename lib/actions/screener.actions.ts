'use server';

import { cache } from 'react';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { jsonBody, researchRequest } from '@/lib/research/client';
import { formatNumber } from '@/lib/format';

const FINNHUB_BASE_URL = 'https://finnhub.io/api/v1';
const FINNHUB_API_KEY = process.env.FINNHUB_API_KEY;

export type ScreenerFilters = {
  marketCapMin: number;
  marketCapMax: number;
  priceMin: number;
  priceMax: number;
  peMin: number;
  peMax: number;
  pbMin: number;
  pbMax: number;
  roeMin: number;
  roeMax: number;
  volumeMin: number;
  betaMin: number;
  betaMax: number;
  sector: string;
  exchange: string;
  assetType: string;
  sortBy: string;
  sortOrder: 'asc' | 'desc';
};

export type ScreenerResult = {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
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

// Lista de símbolos populares para screener (expandible)
const POPULAR_SYMBOLS = [
  'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK.B', 'JNJ', 'V',
  'WMT', 'JPM', 'PG', 'MA', 'UNH', 'HD', 'DIS', 'PYPL', 'NFLX', 'ADBE',
  'CRM', 'CSCO', 'PFE', 'INTC', 'VZ', 'T', 'KO', 'PEP', 'MRK', 'ABT',
  // ETFs
  'SPY', 'QQQ', 'IWM', 'DIA', 'VOO', 'VTI', 'URTH', 'VWO', 'GLD', 'BITO',
];

async function fetchWithTimeout(url: string, timeout = 5000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    throw error;
  }
}

export const screenStocks = cache(async (filters: ScreenerFilters): Promise<ScreenerResult[]> => {
  await requireAuthenticatedUser();
  if (!FINNHUB_API_KEY) {
    console.error('Finnhub API key not configured');
    return [];
  }

  try {
    const results: ScreenerResult[] = [];
    
    // Fetch data for each symbol in parallel
    const promises = POPULAR_SYMBOLS.map(async (symbol) => {
      try {
        // Get quote data
        const quoteUrl = `${FINNHUB_BASE_URL}/quote?symbol=${symbol}&token=${FINNHUB_API_KEY}`;
        const quoteRes = await fetchWithTimeout(quoteUrl);
        
        if (!quoteRes.ok) return null;
        
        const quote = await quoteRes.json();
        
        if (!quote.c || quote.c === 0) return null;
        
        // Get company profile
        const profileUrl = `${FINNHUB_BASE_URL}/stock/profile2?symbol=${symbol}&token=${FINNHUB_API_KEY}`;
        const profileRes = await fetchWithTimeout(profileUrl);
        
        if (!profileRes.ok) return null;
        
        const profile = await profileRes.json();
        
        // Get basic financials (includes PE, PB, etc.)
        const metricsUrl = `${FINNHUB_BASE_URL}/stock/metric?symbol=${symbol}&metric=all&token=${FINNHUB_API_KEY}`;
        const metricsRes = await fetchWithTimeout(metricsUrl);
        
        let metrics: any = { metric: {} };
        if (metricsRes.ok) {
          metrics = await metricsRes.json();
        }
        
        const price = quote.c || 0;
        const change = quote.d || 0;
        const changePercent = quote.dp || 0;
        
        const result: ScreenerResult = {
          symbol,
          name: profile.name || symbol,
          price,
          change,
          changePercent,
          marketCap: profile.marketCapitalization ? profile.marketCapitalization * 1000000 : 0,
          pe: (metrics.metric as any)?.peBasicExclExtraTTM || 0,
          pb: (metrics.metric as any)?.pbAnnual || 0,
          roe: (metrics.metric as any)?.roeTTM || 0,
          volume: quote.v || 0,
          beta: (metrics.metric as any)?.beta || 1.0,
          sector: profile.finnhubIndustry || 'Desconocido',
          exchange: profile.exchange || 'US',
          type: symbol.match(/^[A-Z]{3,4}$/) && ['SPY', 'QQQ', 'IWM', 'VOO', 'VTI', 'URTH', 'VWO', 'GLD', 'BITO'].includes(symbol) ? 'ETF' : 'Stock',
        };
        
        // Apply filters
        if (result.price < filters.priceMin || result.price > filters.priceMax) return null;
        if (result.marketCap < filters.marketCapMin || result.marketCap > filters.marketCapMax) return null;
        if (result.pe > 0 && (result.pe < filters.peMin || result.pe > filters.peMax)) return null;
        if (result.pb > 0 && (result.pb < filters.pbMin || result.pb > filters.pbMax)) return null;
        if (result.roe > 0 && (result.roe < filters.roeMin || result.roe > filters.roeMax)) return null;
        if (result.volume < filters.volumeMin) return null;
        if (result.beta < filters.betaMin || result.beta > filters.betaMax) return null;
        
        if (filters.sector !== 'all' && result.sector !== filters.sector) return null;
        if (filters.exchange !== 'all' && result.exchange !== filters.exchange) return null;
        if (filters.assetType !== 'all' && result.type !== filters.assetType) return null;
        
        return result;
      } catch (error) {
        console.error(`Error fetching data for ${symbol}:`, error);
        return null;
      }
    });
    
    const settled = await Promise.allSettled(promises);
    
    for (const result of settled) {
      if (result.status === 'fulfilled' && result.value) {
        results.push(result.value);
      }
    }
    
    // Sort results
    results.sort((a, b) => {
      const aVal = a[filters.sortBy as keyof ScreenerResult] as number;
      const bVal = b[filters.sortBy as keyof ScreenerResult] as number;
      
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return filters.sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
      }
      
      return 0;
    });
    
    return results;
  } catch (error) {
    console.error('Error in screenStocks:', error);
    return [];
  }
});

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

export type RealScreenerRow = {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  marketCap: number;
  volume: number;
  prevClose: number;
  sector: string;
  exchange: string;
  type: string;
  pe: number | null;
  pb: number | null;
  roe: number | null;
  beta: number | null;
};

export type RealScreenerResponse = {
  source: string;
  as_of: number;
  count: number;
  screener: RealScreenerRow[];
};

/**
 * Screener real: consulta el backend (Finnhub free) con precios y market caps
 * reales del día. Devuelve [] si no hay datos (nunca datos inventados).
 */
export const getScreenerStocksReal = cache(
  async (filters: RealScreenerFilters = {}): Promise<RealScreenerRow[]> => {
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
    return data?.screener ?? [];
  },
);


/** Fair value determinista del Research OS (backend /api/valuation/{ticker}).
 *  Devuelve null si no hay valoracion publicable (nunca datos inventados). */
export const getFairValue = cache(
  async (symbol: string): Promise<number | null> => {
    await requireAuthenticatedUser();
    try {
      const data = await researchRequest<{
        expected_value?: number | null;
        base_value?: number | null;
        publishable?: boolean;
      }>(`/api/valuation/${encodeURIComponent(symbol)}`, { cache: 'no-store' });
      if (!data?.publishable) return null;
      return data.expected_value ?? data.base_value ?? null;
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

export type EngineCriterion = {
  left: string;
  operator: '>' | '>=' | '<' | '<=' | '==' | '!=';
  right: string;
};

export type EngineScreenRow = {
  company_id: number;
  ticker: string;
  name: string;
  matched: boolean;
  rank_value: string | null;
  coverage_percent: number;
  confidence: string;
  latest_data_at: string | null;
  missing_fields: string[];
};

export type EngineScreenResult = {
  criteria: EngineCriterion[];
  ranking_formula: string | null;
  ranking_direction: string;
  company_count: number;
  match_count: number;
  new_match_company_ids?: number[];
  results: EngineScreenRow[];
};

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
