import type { ExtendedQuote } from '@/lib/market/extended-quote';
import { hasCurrentQuote, listingStatus } from '@/lib/research/listing-status';

/**
 * Aviso de ficha sin cotización vigente. Espera la misma cotización que pinta
 * la cabecera: si hay precio actual, no hay aviso contradictorio encima.
 */
export async function ListingStaleBanner({
  exchange,
  priceAsOf,
  quote,
}: {
  exchange: string | null | undefined;
  priceAsOf: string | null | undefined;
  quote?: Promise<ExtendedQuote | null>;
}) {
  const live = quote ? await quote.catch(() => null) : null;
  const now = new Date();
  const listing = listingStatus(exchange, priceAsOf, now, hasCurrentQuote(live, now));
  return listing.stale ? (
    <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200" role="status">
      {listing.message}
    </p>
  ) : null;
}
