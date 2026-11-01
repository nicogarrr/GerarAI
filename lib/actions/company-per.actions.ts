'use server';

import { getStockFinancialDataLight } from '@/lib/actions/finnhub.actions';
import { isUsQuoteLine, quoteSymbolFor } from '@/lib/market/quote-symbol';
import { perState, type PerState } from '@/lib/research/per';

export async function getCompanyPer(
    ticker: string,
    listing: { exchange?: string; currency?: string },
    locale: 'es' | 'en' = 'es',
): Promise<PerState> {
    const normalized = ticker.trim().toUpperCase();
    const quoteSymbol = quoteSymbolFor(listing, normalized);
    const usLine = isUsQuoteLine(listing, normalized);
    if (!quoteSymbol || !usLine) {
        return perState({ quoteSymbol, ticker: normalized, peTTM: undefined, providerAvailable: false, usLine }, locale);
    }
    const light = await getStockFinancialDataLight(normalized).catch(() => null);
    return perState({
        quoteSymbol,
        ticker: normalized,
        peTTM: light?.metrics?.metric?.peTTM,
        providerAvailable: light !== null,
        usLine,
    }, locale);
}
