/**
 * F99/F245: el panel «Expectativa vs realidad» mostraba estados y métricas con
 * la clave cruda del backend (`pending_actual`, `capital_expenditure`,
 * `fcf_margin`…). Estas etiquetas cubren TODO el catálogo que el backend
 * emite hoy (metric_semantics.py + fundamental_review_service.py); el guard
 * comprueba esa cobertura contra la fuente Python, no de memoria.
 *
 * Fallback honesto: un estado desconocido se muestra tal cual (nunca se
 * oculta) y una métrica desconocida se humaniza (`new_metric` → «new metric»).
 */

/** Estados que el backend puede persistir en expectation_reviews.status. */
export const REVIEW_STATUS_LABELS: Record<string, string> = {
    beat: 'superado',
    met: 'cumplido',
    miss: 'no cumplido',
    outside_tolerance: 'fuera de tolerancia',
    pending_actual: 'a la espera de resultados',
    pending: 'pendiente',
    unavailable: 's/d',
};

/**
 * Métricas del backend: unión del registro de semántica
 * (metric_semantics.py) y de FORECAST_METRICS
 * (fundamental_model_repository.py), que es la que puebla
 * ExpectationReview.metric vía forecast.metric.
 */
export const EXPECTATION_METRIC_LABELS: Record<string, string> = {
    revenue: 'Ingresos',
    gross_profit: 'Beneficio bruto',
    operating_income: 'Resultado de explotación',
    ebitda: 'EBITDA',
    net_income: 'Beneficio neto',
    operating_cash_flow: 'Flujo de caja operativo',
    free_cash_flow: 'Flujo de caja libre',
    fcf_per_share: 'FCF por acción',
    fcf_margin: 'Margen FCF',
    roic: 'ROIC',
    net_debt: 'Deuda neta',
    shares_diluted: 'Acciones diluidas',
    churn: 'Churn',
    combined_ratio: 'Combined ratio',
    working_capital_absorption: 'Absorción de capital circulante',
    capital_expenditure: 'CapEx',
    working_capital: 'Capital circulante',
};

/** Estado de una revisión en español; desconocido se muestra tal cual. */
export function reviewStatusLabel(status: string | null | undefined): string {
    if (status == null || status === '') return 's/d';
    return Object.hasOwn(REVIEW_STATUS_LABELS, status) ? REVIEW_STATUS_LABELS[status] : status;
}

/** Métrica en español; desconocida se humaniza sin inventar traducción. */
export function expectationMetricLabel(metric: string | null | undefined): string {
    if (metric == null || metric === '') return 's/d';
    return Object.hasOwn(EXPECTATION_METRIC_LABELS, metric) ? EXPECTATION_METRIC_LABELS[metric] : metric.replaceAll('_', ' ');
}
