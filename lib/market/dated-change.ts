import { researchRequest } from '@/lib/research/client';

/**
 * Variación diaria única: cierres datados de market_prices (backend
 * /api/market/changes, misma función que Movers). Mercado, watchlist y Movers
 * muestran el mismo % para el mismo precio porque leen la misma fuente.
 */
export type DatedChange = {
  price: number;
  currency: string;
  change: number | null;
  changePercent: number | null;
  previousClose: number | null;
  date: string | null;
};

type ChangesResponse = {
  items?: Record<
    string,
    {
      price: number;
  currency: string;
      change: number | null;
      change_pct: number | null;
      previous_close: number | null;
      date: string | null;
    }
  >;
};

/** Solo devuelve tickers con variación comparable; el resto no aparece. */
export async function fetchDatedChanges(symbols: string[]): Promise<Record<string, DatedChange>> {
  const unique = [...new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean))];
  if (unique.length === 0) return {};
  try {
    const data = await researchRequest<ChangesResponse>(
      `/api/market/changes?tickers=${encodeURIComponent(unique.join(','))}`,
      { cache: 'no-store', fast: true },
    );
    const out: Record<string, DatedChange> = {};
    for (const [symbol, item] of Object.entries(data?.items ?? {})) {
      if (item.change_pct === null || item.change_pct === undefined) continue;
      out[symbol.toUpperCase()] = {
        price: item.price,
        currency: item.currency,
        change: item.change,
        changePercent: item.change_pct,
        previousClose: item.previous_close,
        date: item.date,
      };
    }
    return out;
  } catch {
    return {};
  }
}
