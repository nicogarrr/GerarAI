import { TICKER_BADGE_LABELS, TICKER_BADGE_LABELS_EN, tickerBadgesFor } from '@/lib/ticker-badges';

const BADGE_CLASSES: Record<string, string> = {
    portfolio: 'bg-teal-950/60 text-teal-300',
    watchlist: 'bg-amber-950/60 text-amber-300',
};

/**
 * Badges «En cartera / En watchlist» (quick win UX 5). Servidor puro; sin
 * badge para tickers fuera de ambas listas (nunca una afirmación falsa).
 */
export function TickerContextBadges({
    ticker,
    portfolioTickers,
    watchlistTickers,
    locale = 'es',
}: {
    ticker: string;
    portfolioTickers: ReadonlySet<string>;
    watchlistTickers: ReadonlySet<string>;
    locale?: 'es' | 'en';
}) {
    const badges = tickerBadgesFor(ticker, portfolioTickers, watchlistTickers);
    if (badges.length === 0) return null;
    return (
        <span className="mt-1 flex flex-wrap gap-1">
            {badges.map((badge) => (
                <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE_CLASSES[badge]}`}
                    key={badge}
                >
                    {(locale === 'en' ? TICKER_BADGE_LABELS_EN : TICKER_BADGE_LABELS)[badge]}
                </span>
            ))}
        </span>
    );
}
