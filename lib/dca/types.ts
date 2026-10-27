// Tipos de las señales DCA por niveles (GET /api/watchlist/dca-signals).
// Espejo de los modelos Pydantic de data-engine/app/api/routes/watchlist.py.

/** 4..1 = múltiplo de la aportación base; -1 recorte ligero; -2 recorte fuerte. */
export type DcaLevel = 4 | 3 | 2 | 1 | -1 | -2;

export interface DcaZone {
    level: number;
    key: string;
    label: string;
    zone: string;
    color: string;
    fg: string;
}

export interface DcaSignalState extends Omit<DcaZone, 'level'> {
    level: number;
    previous_level: number | null;
    status: 'forming' | 'confirmed' | string;
    period: string;
    signal_date: string;
    close: number;
    currency: string | null;
    currency_label: string | null;
    metrics: Record<string, number | string | null>;
    level_prices: Record<string, number | null>;
    params_version: string;
    data_source: string;
    evaluated_at: string;
    last_alerted_level: number | null;
    last_alerted_period: string | null;
    /** Días desde el último cierre usado. Ausente en backends antiguos. */
    data_age_days?: number | null;
    /** true cuando esa edad supera DCA_MAX_DATA_AGE_DAYS: el nivel no es actual. */
    stale?: boolean;
}

export interface DcaSignalItem {
    symbol: string;
    company_name: string | null;
    sources: string[];
    in_watchlist: boolean;
    in_portfolio: boolean;
    min_level_override: number | null;
    effective_min_level: number;
    alerts_on: boolean;
    state: DcaSignalState | null;
}

export interface DcaSignalsResponse {
    alerts_enabled: boolean;
    /** false = la evaluación diaria está apagada en el servidor (DCA_EVALUATION_ENABLED). Ausente en backends antiguos. */
    evaluation_enabled?: boolean;
    global_min_level: number;
    trims_enabled: boolean;
    channels: string[];
    email_configured: boolean;
    signal_months: number | null;
    zones: DcaZone[];
    items: DcaSignalItem[];
}

export interface DcaEvaluateSummary {
    tracked: number;
    evaluated: number;
    alerted: Array<Record<string, unknown>>;
    skipped: Array<{ symbol: string; reason: string; daily_bars?: number }>;
    errors: Array<{ symbol: string; error: string }>;
    alerts_enabled: boolean;
    params_version: string;
}

/** «¿Cuántas veces estaba más arriba?» (GET /api/watchlist/dca-signals/{symbol}/hit-rates). */
export interface DcaHitRateCell {
    horizon_months: number;
    months: number;
    pct_higher: number | null;
    avg_return: number | null;
}

export interface DcaHitRateRow {
    key: string;
    label: string;
    levels: number[];
    signal_months: number;
    color: string | null;
    cells: DcaHitRateCell[];
}

export interface DcaHitRates {
    symbol: string;
    available: boolean;
    reason: string | null;
    months_completed: number;
    first_period: string | null;
    last_period: string | null;
    horizons: number[];
    params_version: string | null;
    evaluated_at: string | null;
    rows: DcaHitRateRow[];
    disclaimer: string;
}

export interface DcaBacktestPlan {
    key: 'plain' | 'levels' | 'fixed_budget' | string;
    label: string;
    invested: number;
    deployed: number;
    cash_left: number;
    shares: number;
    avg_cost: number | null;
    final_value: number;
    multiple: number | null;
    irr: number | null;
    max_drawdown: number;
    worst_unrealized: number;
    buys: number;
    irr_vs_plain?: number | null;
    value_vs_plain?: number | null;
    shares_per_money_vs_plain?: number | null;
}

export interface DcaBacktest {
    symbol: string;
    available: boolean;
    reason: string | null;
    params_version: string | null;
    currency: string | null;
    currency_label: string | null;
    data_source: string | null;
    first_signal: string | null;
    last_signal: string | null;
    first_buy: string | null;
    last_buy: string | null;
    valued_at_period: string | null;
    final_price: number | null;
    months: number;
    base_amount: number;
    plans: DcaBacktestPlan[];
    levels: { level: number; label: string; color: string; months: number }[];
    hit_rates: DcaHitRates | null;
    disclaimer: string;
}
