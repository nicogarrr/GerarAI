/**
 * Badges de contexto por ticker (quick win UX 5): «En cartera» y
 * «En watchlist» en noticias, movers y listados. Lógica pura y testeable
 * en node; la composición visual vive en components/common/TickerContextBadges.
 *
 * Semántica de «En cartera» (fijada tras dictamen): una posición ABIERTA,
 * es decir, quantity numérica y distinta de cero. El importador IBKR puede
 * persistir quantity=0 (posición cerrada que el ledger no borró): ese
 * ticker NO lleva badge, porque afirmar «En cartera» sin posición sería
 * una afirmación falsa. Una posición corta (quantity < 0) sigue siendo
 * exposición abierta del usuario, así que SÍ lleva badge.
 */
export type TickerBadge = 'portfolio' | 'watchlist';

export const TICKER_BADGE_LABELS: Record<TickerBadge, string> = {
    portfolio: 'En cartera',
    watchlist: 'En watchlist',
};

export const TICKER_BADGE_LABELS_EN: Record<TickerBadge, string> = {
    portfolio: 'In portfolio',
    watchlist: 'On watchlist',
};

/** Tickers con posición abierta (quantity numérica y no nula). */
export function openPositionTickers(
    positions: ReadonlyArray<{ ticker: string; quantity: number | null }>,
): string[] {
    return positions
        .filter((position) => typeof position.quantity === 'number'
            && Number.isFinite(position.quantity)
            && position.quantity !== 0)
        .map((position) => position.ticker.trim().toUpperCase())
        .filter(Boolean);
}

/** Badges que corresponden a un ticker, en orden estable (cartera primero). */
export function tickerBadgesFor(
    ticker: string,
    portfolioTickers: ReadonlySet<string>,
    watchlistTickers: ReadonlySet<string>,
): TickerBadge[] {
    const normalized = ticker.trim().toUpperCase();
    if (!normalized) return [];
    const badges: TickerBadge[] = [];
    if (portfolioTickers.has(normalized)) badges.push('portfolio');
    if (watchlistTickers.has(normalized)) badges.push('watchlist');
    return badges;
}
