/**
 * Etiquetas en español para las métricas canónicas del backend (F321).
 *
 * Cobertura: claves de FinancialFact (ingesta SEC/ESEF/FMP + derivadas en
 * financial_ingestion_service.py) y de CalculatedMetric
 * (metric_calculation_service.py). La ficha las mostraba en snake_case crudo
 * («net_debt_to_ebitda»). Si el backend añade una clave nueva, el fallback
 * la humaniza (guiones bajos -> espacios) en vez de ocultarla.
 */
export const METRIC_LABELS: Record<string, string> = {
    market_cap: 'Capitalización bursátil',
    roce: 'Rentabilidad del capital empleado (ROCE)',
    incremental_roic: 'ROIC incremental',
    stock_based_compensation: 'Remuneración en acciones',
    owner_earnings: 'Beneficio del propietario',

    // Hechos canónicos (financial_ingestion_service.py)
    revenue: 'Ingresos',
    gross_profit: 'Beneficio bruto',
    operating_income: 'Resultado de explotación',
    income_before_tax: 'Beneficio antes de impuestos',
    income_tax_expense: 'Gasto por impuesto sobre beneficios',
    interest_expense: 'Gastos financieros',
    net_income: 'Beneficio neto',
    ebitda: 'EBITDA',
    eps_diluted: 'BPA diluido',
    shares_diluted: 'Acciones diluidas (media)',
    total_assets: 'Activos totales',
    total_liabilities: 'Pasivos totales',
    total_equity: 'Patrimonio neto',
    total_debt: 'Deuda total',
    net_debt: 'Deuda neta',
    market_price: 'Precio de mercado',
    cash_and_equivalents: 'Efectivo y equivalentes',
    goodwill: 'Fondo de comercio',
    intangible_assets: 'Activos intangibles',
    operating_lease_liabilities: 'Pasivos por arrendamientos operativos',
    operating_cash_flow: 'Flujo de caja operativo',
    capital_expenditure: 'Inversión de capital (CapEx)',
    depreciation_amortization: 'Depreciación y amortización',
    free_cash_flow: 'Flujo de caja libre',
    dividends_paid: 'Dividendos pagados',
    common_stock_repurchased: 'Recompra de acciones propias',
    fcf_margin: 'Margen FCF',
    gross_margin: 'Margen bruto',
    operating_margin: 'Margen operativo',
    net_margin: 'Margen neto',
    effective_tax_rate: 'Tipo impositivo efectivo',
    debt_to_equity: 'Deuda / patrimonio',
    revenue_growth: 'Crecimiento de ingresos',
    eps: 'BPA',
    fcf_per_share: 'Flujo de caja libre por acción',
    approval_probability: 'probabilidad de aprobación',
    cash_runway: 'autonomía de caja',
    dilution_risk: 'riesgo de dilución',
    regulatory_risk: 'riesgo regulatorio',
    roe_5y: 'ROE (5 años)',
    roa_5y: 'ROA (5 años)',
    owner_earnings_5y: 'Beneficio del propietario (5 años)',
    capex_to_da_5y: 'CapEx / depreciación y amortización (5 años)',
    quality_moat_score: 'Marco de calidad',
    quality_moat_score_v2: 'Marco de calidad ampliado',
    // Métricas calculadas (metric_calculation_service.py)
    roic: 'ROIC',
    roic_adjusted: 'ROIC ajustado',
    roe: 'ROE',
    roa: 'ROA',
    fcf_conversion: 'Conversión de FCF',
    net_debt_to_ebitda: 'Deuda neta / EBITDA',
    asset_life: 'Vida útil media de los activos',
    gross_investment: 'Inversión bruta',
    inflation_adjusted_gross_cash_flow: 'Flujo de caja bruto ajustado por inflación',
    non_depreciating_assets: 'Activos no depreciables',
    terminal_non_depreciating_assets: 'Activos no depreciables (terminal)',
    fcf_margin_5y: 'Margen FCF (5 años)',
    net_margin_5y: 'Margen neto (5 años)',
    wacc: 'WACC',
    cfroi: 'CFROI',
    cfroi_approx: 'CFROI aproximado',
    // Drivers, KPIs y entradas del modelo a largo plazo (long_term_model_service)
    traceable_wacc: 'WACC con fuente trazable',
    no_revenue_reported: 'ingresos reportados (empresa sin ingresos: el DCF no aplica)',
    annual_revenue_missing: 'ingresos anuales (solo hay datos trimestrales)',
    revenue_history_two_periods: 'historial de ingresos de dos periodos',
    normalized_fcf_margin: 'margen FCF normalizado',
    price: 'precio',
    volume: 'volumen',
    mix: 'mezcla de producto',
    organic_growth: 'crecimiento orgánico',
    FCF_margin: 'margen FCF',
    ROIC: 'ROIC',
    share_count: 'número de acciones',
    working_capital: 'capital circulante',
    terminal_growth: 'crecimiento terminal',
    addressable_subscribers: 'suscriptores direccionables',
    capacity_per_satellite: 'capacidad por satélite',
    monthly_arpu: 'ARPU mensual',
    normalized_fcf_or_fcf_margin: 'FCF normalizado o margen FCF',
    penetration: 'penetración',
    price_per_gb: 'precio por GB',
    revenue_share: 'reparto de ingresos',
    satellites: 'satélites',
    utilization: 'utilización',
};

/** Etiqueta en español de una métrica; humaniza la clave si es desconocida. */
export function metricLabel(metric: string): string {
    const known = METRIC_LABELS[metric] ?? METRIC_LABELS[metric.toLowerCase()];
    if (known) return known;
    return metric.replaceAll('_', ' ');
}
