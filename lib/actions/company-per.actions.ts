'use server';

import { getStockFinancialDataLight } from '@/lib/actions/finnhub.actions';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { perState, type PerState } from '@/lib/research/per';

export async function getCompanyPer(
    ticker: string,
    listing: { exchange?: string; currency?: string },
): Promise<PerState> {
    const normalized = ticker.trim().toUpperCase();
    const quoteSymbol = quoteSymbolFor(listing, normalized);
    if (!quoteSymbol || quoteSymbol !== normalized) {
        return perState({ quoteSymbol, ticker: normalized, peTTM: undefined, providerAvailable: false });
    }
    const light = await getStockFinancialDataLight(normalized).catch(() => null);
    return perState({
        quoteSymbol,
        ticker: normalized,
        peTTM: light?.metrics?.metric?.peTTM,
        providerAvailable: light !== null,
    });
}
