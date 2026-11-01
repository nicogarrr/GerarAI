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

// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

/** Estados que el backend puede persistir en expectation_reviews.status (clave del diccionario). */
const REVIEW_STATUS_KEYS: Record<string, TranslationKey> = {
    beat: 'research.expect.status.beat',
    met: 'research.expect.status.met',
    miss: 'research.expect.status.miss',
    outside_tolerance: 'research.expect.status.outsideTolerance',
    pending_actual: 'research.expect.status.pendingActual',
    pending: 'research.expect.status.pending',
    unavailable: 'research.expect.status.unavailable',
};

/**
 * Métricas del backend: unión del registro de semántica
 * (metric_semantics.py) y de FORECAST_METRICS
 * (fundamental_model_repository.py), que es la que puebla
 * ExpectationReview.metric vía forecast.metric.
 */
const EXPECTATION_METRIC_KEYS: Record<string, TranslationKey> = {
    revenue: 'research.expect.metric.revenue',
    gross_profit: 'research.expect.metric.grossProfit',
    operating_income: 'research.expect.metric.operatingIncome',
    ebitda: 'research.expect.metric.ebitda',
    net_income: 'research.expect.metric.netIncome',
    operating_cash_flow: 'research.expect.metric.operatingCashFlow',
    free_cash_flow: 'research.expect.metric.freeCashFlow',
    fcf_per_share: 'research.expect.metric.fcfPerShare',
    fcf_margin: 'research.expect.metric.fcfMargin',
    roic: 'research.expect.metric.roic',
    net_debt: 'research.expect.metric.netDebt',
    shares_diluted: 'research.expect.metric.sharesDiluted',
    churn: 'research.expect.metric.churn',
    combined_ratio: 'research.expect.metric.combinedRatio',
    working_capital_absorption: 'research.expect.metric.workingCapitalAbsorption',
    capital_expenditure: 'research.expect.metric.capitalExpenditure',
    working_capital: 'research.expect.metric.workingCapital',
};

const inSpanish = (keys: Record<string, TranslationKey>): Record<string, string> =>
    Object.fromEntries(Object.entries(keys).map(([id, key]) => [id, esT(key)]));

/** Etiquetas en español (referencia; el guard comprueba la cobertura del catálogo). */
export const REVIEW_STATUS_LABELS: Record<string, string> = inSpanish(REVIEW_STATUS_KEYS);
export const EXPECTATION_METRIC_LABELS: Record<string, string> = inSpanish(EXPECTATION_METRIC_KEYS);

/** Estado de una revisión en el idioma elegido; desconocido se muestra tal cual. */
export function reviewStatusLabel(status: string | null | undefined, ti: TiFn = esT): string {
    if (status == null || status === '') return ti('research.model.na');
    return Object.hasOwn(REVIEW_STATUS_KEYS, status) ? ti(REVIEW_STATUS_KEYS[status]) : status;
}

/** Métrica en el idioma elegido; desconocida se humaniza sin inventar traducción. */
export function expectationMetricLabel(metric: string | null | undefined, ti: TiFn = esT): string {
    if (metric == null || metric === '') return ti('research.model.na');
    return Object.hasOwn(EXPECTATION_METRIC_KEYS, metric) ? ti(EXPECTATION_METRIC_KEYS[metric]) : metric.replaceAll('_', ' ');
}
