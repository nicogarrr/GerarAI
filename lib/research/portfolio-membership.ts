export type MembershipPosition = { ticker: string; quantity: number };

/** Same open-position rule as the portfolio, without valuation or FX data. */
export function portfolioMembership(rows: MembershipPosition[]): Set<string> {
    return new Set(rows.filter((row) => row.quantity !== 0)
        .map((row) => row.ticker.trim().toUpperCase()).filter(Boolean));
}
