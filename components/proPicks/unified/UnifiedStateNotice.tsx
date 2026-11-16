import type { TranslateFn } from '@/lib/i18n/translate';

export const UNIFIED_REASON_KEYS = {
    delisted: 'propicks.unifiedStates.reasons.delisted',
    instrument_cancelled: 'propicks.unifiedStates.reasons.instrument_cancelled',
    trading_suspended: 'propicks.unifiedStates.reasons.trading_suspended',
    quality_failed: 'propicks.unifiedStates.reasons.quality_failed',
    sector_model_required: 'propicks.unifiedStates.reasons.sector_model_required',
    quality_funnel_not_passed: 'propicks.unifiedStates.reasons.quality_funnel_not_passed',
    leverage_missing_or_high: 'propicks.unifiedStates.reasons.leverage_missing_or_high',
    fundamentals_stale_or_missing: 'propicks.unifiedStates.reasons.fundamentals_stale_or_missing',
    fcf_periods_not_comparable: 'propicks.unifiedStates.reasons.fcf_periods_not_comparable',
    fcf_not_positive_and_growing: 'propicks.unifiedStates.reasons.fcf_not_positive_and_growing',
    liquidity_missing_or_low: 'propicks.unifiedStates.reasons.liquidity_missing_or_low',
    market_cap_missing_or_low: 'propicks.unifiedStates.reasons.market_cap_missing_or_low',
    identity_disputed: 'propicks.unifiedStates.reasons.identity_disputed',
    identity_invalid: 'propicks.unifiedStates.reasons.identity_invalid',
    identity_unverified: 'propicks.unifiedStates.reasons.identity_unverified',
    valuation_stale: 'propicks.unifiedStates.reasons.valuation_stale',
    valuation_disputed: 'propicks.unifiedStates.reasons.valuation_disputed',
    valuation_invalid: 'propicks.unifiedStates.reasons.valuation_invalid',
    quality_score_stale: 'propicks.unifiedStates.reasons.quality_score_stale',
    quality_score_disputed: 'propicks.unifiedStates.reasons.quality_score_disputed',
    quality_score_invalid: 'propicks.unifiedStates.reasons.quality_score_invalid',
    quality_unknown: 'propicks.unifiedStates.reasons.quality_unknown',
    price_missing: 'propicks.unifiedStates.reasons.price_missing',
    extreme_value: 'propicks.unifiedStates.reasons.extreme_value',
    stale: 'propicks.unifiedStates.reasons.stale',
    non_finite: 'propicks.unifiedStates.reasons.non_finite',
    block_error: 'propicks.unifiedStates.reasons.block_error',
} as const;

export const STATE_KEYS = {
    empty: 'propicks.unifiedStates.states.empty',
    partial: 'propicks.unifiedStates.states.partial',
    error: 'propicks.unifiedStates.states.error',
    stale: 'propicks.unifiedStates.states.stale',
    retained: 'propicks.unifiedStates.states.retained',
} as const;

export const ERROR_KEYS = {
    timeout: 'propicks.unifiedStates.errors.timeout',
    unauthenticated: 'propicks.unifiedStates.errors.unauthenticated',
    forbidden: 'propicks.unifiedStates.errors.forbidden',
    rate_limited: 'propicks.unifiedStates.errors.rate_limited',
    unavailable: 'propicks.unifiedStates.errors.unavailable',
    invalid_response: 'propicks.unifiedStates.errors.invalid_response',
} as const;

const BLOCK_KEYS = {
    quality: 'propicks.unified.colQuality',
    valuation: 'propicks.unified.colValuation',
    dca: 'propicks.unified.colDca',
    tracking: 'propicks.unified.trackingTitle',
} as const;

export interface UnifiedStateNoticeProps {
    t: TranslateFn;
    state: 'ok' | keyof typeof STATE_KEYS;
    errorKind?: keyof typeof ERROR_KEYS;
    reasonCodes?: readonly string[];
    affectedBlocks?: readonly string[];
    /** Already formatted source date, never the payload creation time. */
    asOf?: string | null;
    retryAfterSeconds?: number | null;
}

export function UnifiedStateNotice({ t, state, errorKind, reasonCodes = [], affectedBlocks = [], asOf, retryAfterSeconds }: UnifiedStateNoticeProps) {
    if (state === 'ok') return null;
    const seconds = typeof retryAfterSeconds === 'number' && Number.isFinite(retryAfterSeconds) && retryAfterSeconds > 0 ? Math.ceil(retryAfterSeconds) : null;
    return <aside role={state === 'error' ? 'alert' : 'status'} className="space-y-2 rounded-lg border border-amber-700/60 bg-amber-950/20 p-4 text-sm leading-6 text-amber-100">
        <p>{t(Object.hasOwn(STATE_KEYS, state) ? STATE_KEYS[state] : 'propicks.unifiedStates.states.error')}</p>
        {state === 'error' && errorKind && <p>{t(Object.hasOwn(ERROR_KEYS, errorKind) ? ERROR_KEYS[errorKind] : 'propicks.unifiedStates.errors.unavailable')}</p>}
        {errorKind === 'rate_limited' && seconds !== null && <p>{t('propicks.unifiedStates.retryAfter', { seconds })}</p>}
        {affectedBlocks.length > 0 && <p>{affectedBlocks.map(block => t(Object.hasOwn(BLOCK_KEYS, block) ? BLOCK_KEYS[block as keyof typeof BLOCK_KEYS] : 'propicks.unifiedStates.unknownReason')).join(', ')}</p>}
        {(state === 'stale' || state === 'retained') && asOf && <p>{t('propicks.unifiedStates.asOf', { date: asOf })}</p>}
        {reasonCodes.length > 0 && <ul className="list-inside list-disc">{[...new Set(reasonCodes)].map(code => <li key={code}>{t(Object.hasOwn(UNIFIED_REASON_KEYS, code) ? UNIFIED_REASON_KEYS[code as keyof typeof UNIFIED_REASON_KEYS] : 'propicks.unifiedStates.unknownReason')}</li>)}</ul>}
    </aside>;
}

export const UNIFIED_ELIGIBILITY_KEYS = {
    investigate: 'propicks.unifiedStates.eligibility.investigate',
    quality_waiting_price: 'propicks.unifiedStates.eligibility.quality_waiting_price',
    review_data: 'propicks.unifiedStates.eligibility.review_data',
    excluded: 'propicks.unifiedStates.eligibility.excluded',
} as const;

/** Display helper only. Missing data are never coerced to a numeric score. */
export function unifiedMissingLabel(t: TranslateFn): string {
    return t('propicks.unifiedStates.missing');
}
