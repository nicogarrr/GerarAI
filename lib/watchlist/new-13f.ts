/**
 * «Nuevas posiciones 13F» por empresa de la watchlist: view-model puro del
 * contrato de GET /api/watchlist/new-13f (agregación sobre
 * institutional_holders, 0026d2108).
 *
 * Reglas honestas: count null = sin dato (nunca 0); «sin_detalle» conserva el
 * conteo sin inventar la lista; valor ausente = N/D (nunca estimado mezclado,
 * decisión 2026-11-16); el 0 real sí se muestra.
 */

export interface New13fHolderRow {
    cik: string;
    name: string | null;
    shares: number;
    /** Valor declarado al cierre del trimestre (USD); null = no declarado. */
    value_usd: number | null;
    filing_url?: string | null;
    value_filing_urls?: string[];
}

export interface New13fPositions {
    /** Pass-through del backend (ok | valor_parcial | sin_detalle | sin_datos). */
    status: string;
    /** null = sin dato (no confundir con 0 = de verdad no hay nuevas). */
    count: number | null;
    value_known_count: number | null;
    top_by_shares: New13fHolderRow[];
    top_by_value: New13fHolderRow[];
    value_basis?: string;
}

/** Item tal cual lo devuelve GET /api/watchlist/new-13f. */
export interface WatchlistNew13fItem {
    ticker: string;
    status: string;
    reason?: string | null;
    period?: string | null;
    new_positions?: New13fPositions | null;
}

export type New13fStatus = 'ok' | 'count_only' | 'no_data';

export interface New13fTopRow {
    id: string;
    fund: string;
    shares: number;
    /** Valor declarado (USD); null = N/D, nunca estimado. */
    valueApprox: number | null;
    valueBasis: 'declared';
}

export interface WatchlistNew13f {
    ticker: string;
    status: New13fStatus;
    /** Trimestre del 13F (YYYY-MM-DD); null si no hay dato. */
    period: string | null;
    countNew: number | null;
    topNew: New13fTopRow[];
    /** Suma de acciones de las mayores mostradas. */
    topTotalShares: number;
    /** valor_parcial: el conteo es real pero no todos los valores están declarados. */
    partial: boolean;
}

const NO_DATA: Omit<WatchlistNew13f, 'ticker'> = {
    status: 'no_data',
    period: null,
    countNew: null,
    topNew: [],
    topTotalShares: 0,
    partial: false,
};

export function mapNewPositions(ticker: string, item: Omit<WatchlistNew13fItem, 'ticker'>): WatchlistNew13f {
    const positions = item.new_positions ?? null;
    if (positions === null || positions.count === null || positions.count === undefined || positions.status === 'sin_datos') {
        return { ticker, ...NO_DATA, period: item.period ?? null };
    }
    if (positions.status === 'sin_detalle') {
        // Snapshot legado: el conteo es real pero la lista no se guardó.
        return { ticker, ...NO_DATA, status: 'count_only', countNew: positions.count, period: item.period ?? null };
    }
    const topNew = (positions.top_by_shares ?? []).slice(0, 5).map((row) => ({
        id: row.cik,
        fund: row.name ?? row.cik,
        shares: row.shares,
        valueApprox: row.value_usd ?? null,
        valueBasis: 'declared' as const,
    }));
    return {
        ticker,
        status: 'ok',
        period: item.period ?? null,
        countNew: positions.count,
        topNew,
        topTotalShares: topNew.reduce((sum, row) => sum + row.shares, 0),
        partial: positions.status === 'valor_parcial',
    };
}
