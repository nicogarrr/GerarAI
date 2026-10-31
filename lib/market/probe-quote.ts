import { chartPriceUnit } from '@/lib/market/chart-price-units';
import { mapBackendYahooQuote, type ProviderQuotePayload } from '@/lib/market/quote-freshness';

export type ProbeQuote = { price: number; currency: string | null };

/** Precio + divisa de una candidata del sondeo de oportunidades desde el
 * lote del backend (POST /api/market/quotes/batch, Yahoo con cache Redis de
 * 60s). Misma normalizacion de unidades que la watchlist (GBp -> GBP): el
 * precio y la divisa salen de la MISMA fuente, nunca mezclados.
 * null = sin dato util: el caller cae al camino por candidata (Finnhub-first). */
export function probeQuoteFromBackend(payload: ProviderQuotePayload | null | undefined): ProbeQuote | null {
    const quote = mapBackendYahooQuote(payload);
    if (!quote || !(quote.c > 0)) return null;
    const unit = chartPriceUnit(quote.currency ?? null);
    if (!unit) return null;
    return { price: quote.c / unit.divisor, currency: unit.currency };
}
