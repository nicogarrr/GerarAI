// Static identity data, NOT prices. Mirrored from REVIEWED_ISSUERS in
// data-engine/app/services/cnmv_mapping.py (CNMV-reviewed .MC aliases only).
// @ts-expect-error TS5097: explicit path also supports node strip-types tests.
import { foldSearchQuery } from '../search-query.ts';
import listings from './spanish-listings.json' with { type: 'json' };

export function searchSpanishListings(query: string): StockWithWatchlistStatus[] {
    const folded = foldSearchQuery(query).toUpperCase();
    if (folded.length < 2) return [];
    return listings.filter((row) => [row.symbol, row.name, ...row.aliases]
        .some((value) => foldSearchQuery(value).toUpperCase().includes(folded)))
        .slice(0, 15).map((row) => ({
            symbol: row.symbol, name: row.name, exchange: 'BME',
            type: 'Common Stock', isInWatchlist: false,
        }));
}
