import type { ResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import type { WatchlistEntryData } from '@/lib/actions/watchlist.actions';

/** Fila base «sin datos»: símbolo/nombre/bolsa/divisa del master y toda la
 *  parte cotizada a null (las celdas pintan «N/D» honesto, nunca 0). Antes
 *  nacía en tres sitios (la entrada real y los dos respaldos de la página:
 *  presupuesto agotado y fallo de red) y las tres copias tenían que crecer a
 *  la par; ahora la forma vacía es una sola y al añadir un campo cotizado hay
 *  un único sitio donde nace en null. */
export function emptyWatchlistEntry(
    symbol: string,
    basics: ResearchCompanyBasics | null,
    quoteSymbol: string | null,
): WatchlistEntryData {
    return {
        symbol,
        name: basics?.name || symbol,
        exchange: basics?.exchange || null,
        currency: basics?.currency || null,
        price: null,
        change: null,
        changePercent: null,
        marketCap: null,
        marketCapDerived: false,
        peRatio: null,
        peKind: null,
        peSource: null,
        peSourceLabel: null,
        priceKind: null,
        priceAsOf: null,
        metricsNotApplicable: false,
        quoteSymbol,
    };
}
