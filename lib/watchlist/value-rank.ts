/** Puesto relativo por valor justo / precio (backend: app/valuation/relative_rank.py).
 *  Sustituye a la etiqueta binaria «infravalorada / sobrevalorada», que en el
 *  backtest no anticipaba nada a 12 meses; el puesto sí ordenó a 24 meses. */
/** Lo medido del puesto (backend: app/data/value_rank_evidence.json). El texto lee de aquí sus cifras. */
export type ValueRankEvidence = {
    universe: string;
    companies: number;
    sample_years: string;
    horizon_months: number;
    cheapest_vs_dearest_quintile_pts: ReadonlyArray<{ period: string; pts: number }>;
    undervalued_beat_spy_12m: number;
    rest_beat_spy_12m: number;
};
export type ValueRank = { quintile: number; cheaper_than_pct: number; peers: number; evidence?: ValueRankEvidence | null };

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

/** Parámetros del texto «medido» del puesto, sacados del artefacto medido (o null: sin cifras, no se dice nada).
 *  ``signed`` formatea puntos con signo (+0,4); ``join`` une la lista en el idioma (Intl.ListFormat). */
export function valueRankEvidenceParams(
    evidence: ValueRankEvidence | null | undefined,
    signed: (value: number) => string,
    join: (parts: string[]) => string,
): Record<string, string | number> | null {
    const spreads = evidence?.cheapest_vs_dearest_quintile_pts?.filter((row) => Number.isFinite(row.pts) && row.period) ?? [];
    if (!evidence || spreads.length === 0) return null;
    const pct = (share: number) => Math.round(share * 100);
    if (!Number.isFinite(evidence.undervalued_beat_spy_12m) || !Number.isFinite(evidence.rest_beat_spy_12m)) return null;
    return {
        universe: evidence.universe,
        companies: evidence.companies,
        years: evidence.sample_years,
        months: evidence.horizon_months,
        spreads: join(spreads.map((row) => `${signed(row.pts)} (${row.period})`)),
        under: pct(evidence.undervalued_beat_spy_12m),
        rest: pct(evidence.rest_beat_spy_12m),
    };
}
