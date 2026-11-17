export type StressWindow = {
    year: number; status: 'calculated' | 'SIN_DATOS'; reason?: string;
    return?: number; max_drawdown?: number; peak_date?: string; trough_date?: string;
    start_date?: string; end_date?: string; observations?: number;
    recovery_date?: string | null; recovery_days?: number | null;
    recovery_status?: 'recovered' | 'history_gaps' | 'not_recovered'; last_observation?: string;
    missing_tickers?: string[];
};
export type HistoricalStressReport = {
    generated_at: string; mode: 'company' | 'portfolio'; data_kind: string;
    portfolio: StressWindow[];
    companies: Array<{
        ticker: string; weight: number | null; weight_as_of: string | null;
        source: string; source_url: string | null; fetched_at: string | null; currency: string | null;
        windows: StressWindow[];
    }>;
};
