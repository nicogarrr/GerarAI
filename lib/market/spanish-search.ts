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

export function mergeSpanishListings(
    query: string,
    local: StockWithWatchlistStatus[],
    remote: StockWithWatchlistStatus[],
): StockWithWatchlistStatus[] {
    const q = foldSearchQuery(query).toUpperCase();
    const preferred = new Set(listings.filter((row) =>
        [row.name, ...row.aliases.filter((alias) => !alias.includes('.'))]
            .some((name) => {
                const value = foldSearchQuery(name).toUpperCase();
                return value === q || value.startsWith(q);
            }),
    ).map((row) => row.symbol));
    const ordered = [
        ...local.filter((row) => preferred.has(row.symbol)),
        ...remote,
        ...local.filter((row) => !preferred.has(row.symbol)),
    ];
    return ordered.filter((row, index) => ordered.findIndex((other) =>
        other.symbol.toUpperCase() === row.symbol.toUpperCase()) === index).slice(0, 15);
}
