/** Puesto relativo por valor justo / precio (backend: app/valuation/relative_rank.py).
 *  Sustituye a la etiqueta binaria «infravalorada / sobrevalorada», que en el
 *  backtest no anticipaba nada a 12 meses; el puesto sí ordenó a 24 meses. */
export type ValueRank = { quintile: number; cheaper_than_pct: number; peers: number };

const RANK_KEYS = [
    'watchlist.page.fairValue.rankQ1',
    'watchlist.page.fairValue.rankQ2',
    'watchlist.page.fairValue.rankQ3',
    'watchlist.page.fairValue.rankQ4',
    'watchlist.page.fairValue.rankQ5',
] as const;
export type ValueRankKey = (typeof RANK_KEYS)[number];

export function valueRankKey(rank: ValueRank | null | undefined): ValueRankKey | null {
    if (!rank || !Number.isInteger(rank.quintile) || rank.quintile < 1 || rank.quintile > 5) return null;
    return RANK_KEYS[rank.quintile - 1];
}

/** Recuento para el resumen de la watchlist: extremos (quintil 1 y 5) y nº de comparables. */
export function valueRankSummary(ranks: ReadonlyArray<ValueRank | null | undefined>): { cheap: number; dear: number; peers: number; ranked: number } {
    const valid = ranks.filter((rank): rank is ValueRank => valueRankKey(rank) !== null);
    return {
        cheap: valid.filter((rank) => rank.quintile === 1).length,
        dear: valid.filter((rank) => rank.quintile === 5).length,
        peers: valid.reduce((max, rank) => Math.max(max, rank.peers), 0),
        ranked: valid.length,
    };
}
