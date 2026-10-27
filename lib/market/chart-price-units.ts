/** Normalize OHLC from its own response metadata, never from price magnitude. */
export function chartPriceUnit(unit: string | null | undefined): { currency: string; divisor: number } | null {
    const raw = unit?.trim();
    if (!raw) return null;
    if (['GBp', 'GBX', 'GBPENCE'].includes(raw)) return { currency: 'GBP', divisor: 100 };
    if (['ZAc', 'ZAC'].includes(raw)) return { currency: 'ZAR', divisor: 100 };
    if (['ILA', 'ILa', 'ILX'].includes(raw)) return { currency: 'ILS', divisor: 100 };
    return /^[A-Za-z]{3}$/.test(raw) ? { currency: raw.toUpperCase(), divisor: 1 } : null;
}

export function normalizeChartPriceUnits<T extends { open?: number | null; high?: number | null; low?: number | null; close: number }>(
    bars: readonly T[], input: { ticker: string; currency?: string | null; candleCurrency?: string | null },
): { bars: T[]; currency: string | null } {
    const declared = chartPriceUnit(input.currency);
    const candle = chartPriceUnit(input.candleCurrency);
    const ambiguous = /\.(L|JO|TA)$/i.test(input.ticker) || (declared?.divisor ?? 1) !== 1;
    // Legacy ordinary major-unit candles remain supported. Minor-unit listings
    // require explicit metadata from this response, even if the master says GBX.
    const unit = candle ?? (!ambiguous && !input.candleCurrency ? declared : null);
    if (!unit || (declared && declared.currency !== unit.currency)) return { bars: [], currency: null };
    const amount = (value: number | null | undefined) => value == null ? null : value / unit.divisor;
    return { currency: unit.currency, bars: bars.map((bar) => ({ ...bar, open: amount(bar.open), high: amount(bar.high), low: amount(bar.low), close: bar.close / unit.divisor })) };
}
