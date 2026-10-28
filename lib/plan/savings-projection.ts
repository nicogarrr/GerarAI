export type SavingsScenario = {
    years: number;
    annual_total_return: number;
    contributed: number;
    terminal_value: number;
    simulated_return: number;
    terminal_value_today_money: number;
    annual_inflation: number;
    terminal_dividend_yield: number;
    terminal_annual_gross_dividend: number;
    terminal_monthly_gross_dividend_equivalent: number;
    net_dividend: null;
};
export type SavingsProjection = {
    plan_exists: boolean;
    preview: boolean;
    monthly_contribution: number | null;
    currency: string | null;
    horizon_years: number | null;
    initial_capital: number;
    portfolio_included: boolean;
    status: 'ok' | 'no_plan' | 'currency_missing';
    scenarios: SavingsScenario[];
    assumptions: string[];
};
export type SavingsPreviewInput = { monthly: number; years: number; currency: string; dividendYield: number; inflation: number };
