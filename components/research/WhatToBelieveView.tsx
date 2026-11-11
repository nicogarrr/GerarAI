'use client';
import type { ImpliedWacc, WhatToBelieve } from '@/lib/research/what-to-believe';
import { useFormat, useT } from '@/lib/i18n/client';

function reasonLabel(t: ReturnType<typeof useT>, reason: string | null | undefined): string {
    switch (reason) {
        case null:
        case undefined:
        case 'engine_not_dcf': return t('research.whatToBelieve.reasons.engine_not_dcf');
        case 'no_base_value': return t('research.whatToBelieve.reasons.no_base_value');
        case 'no_price': return t('research.whatToBelieve.reasons.no_price');
        default: return t('research.whatToBelieve.reasons.valuation_unavailable');
    }
}

export function WhatToBelieveSkeleton() {
    const t = useT();
    return (
        <section aria-busy="true" className="rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="what-to-believe-loading">
            <p className="text-sm text-gray-400" role="status">{t('research.whatToBelieve.loading')}</p>
            <div aria-hidden="true" className="mt-3 space-y-2">
                <div className="h-3 w-2/3 animate-pulse rounded bg-gray-800" />
                <div className="h-3 w-1/2 animate-pulse rounded bg-gray-800" />
            </div>
        </section>
    );
}

type Formatters = { money: (v: number) => string; pct: (v: number) => string };

function waccSentence(t: ReturnType<typeof useT>, f: Formatters, solved: ImpliedWacc, used: number | null | undefined, kind: 'price' | 'consensus'): string | null {
    const price = solved.target_price;
    if (price === null || price === undefined) return null;
    const usedText = used === null || used === undefined ? null : f.pct(used);
    const [min, max] = solved.bounds ?? [];
    if (solved.status === 'ok' && solved.wacc !== null && solved.wacc !== undefined) {
        if (kind === 'consensus') return t('research.whatToBelieve.waccConsensus', { price: f.money(price), implied: f.pct(solved.wacc) });
        return usedText
            ? t('research.whatToBelieve.waccPrice', { price: f.money(price), implied: f.pct(solved.wacc), used: usedText })
            : t('research.whatToBelieve.waccPriceNoUsed', { price: f.money(price), implied: f.pct(solved.wacc) });
    }
    if (solved.status === 'out_of_range' && solved.direction === 'below_min' && min !== undefined) {
        return t(kind === 'consensus' ? 'research.whatToBelieve.waccConsensusBelow' : 'research.whatToBelieve.waccBelow', { price: f.money(price), min: f.pct(min) });
    }
    if (solved.status === 'out_of_range' && solved.direction === 'above_max' && max !== undefined) {
        return t(kind === 'consensus' ? 'research.whatToBelieve.waccConsensusAbove' : 'research.whatToBelieve.waccAbove', { price: f.money(price), max: f.pct(max) });
    }
    return kind === 'price' ? t('research.whatToBelieve.waccNotAvailable') : null;
}

/** Brecha precio / DCF base por debajo de la cual se dice «en línea» (±0,5 %). */
const IN_LINE_GAP = 0.005;

/**
 * Conclusión primero: cuánto vale la acción en nuestro DCF base frente al
 * precio de hoy. Sin ella la tarjeta solo hablaba de WACC y el inversor tenía
 * que ir a otra sección a ver si el precio está por encima o por debajo.
 * Sin valor base o sin precio positivos no hay frase (nunca cifras inventadas).
 */
function verdictSentence(t: ReturnType<typeof useT>, f: Formatters, base: number | null | undefined, price: number | null | undefined): string | null {
    if (base === null || base === undefined || price === null || price === undefined || !(base > 0) || !(price > 0)) return null;
    const gap = price / base - 1;
    const vars = { value: f.money(base), price: f.money(price) };
    if (Math.abs(gap) < IN_LINE_GAP) return t('research.whatToBelieve.verdictInLine', vars);
    return t(gap > 0 ? 'research.whatToBelieve.verdictAbove' : 'research.whatToBelieve.verdictBelow', { ...vars, gap: f.pct(Math.abs(gap)) });
}

export function WhatToBelieveView({ data }: { data: WhatToBelieve | null }) {
    const t = useT();
    const fmt = useFormat();
    const cur = data?.currency?.trim() || null;
    const f: Formatters = {
        money: (v) => (cur ? fmt.formatPrice(v, cur) : fmt.formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })),
        pct: (v) => fmt.formatPercent(v, { fromRatio: true, digits: 1 }),
    };
    const priceLine = data?.implied_wacc_price ? waccSentence(t, f, data.implied_wacc_price, data.wacc_used, 'price') : null;
    const consensusLine = data?.implied_wacc_consensus ? waccSentence(t, f, data.implied_wacc_consensus, data.wacc_used, 'consensus') : null;
    const verdict = data?.status === 'ok' ? verdictSentence(t, f, data.base_value, data.current_price) : null;
    const growth = data?.implied_growth;
    const exit = data?.exit_multiple;
    const multiple = (v: number) => fmt.formatNumber(v, { maximumFractionDigits: 0 });
    return (
        <section aria-labelledby="what-to-believe-title" className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="what-to-believe">
            <h2 className="text-base font-semibold text-gray-100" id="what-to-believe-title">{t('research.whatToBelieve.title')}</h2>
            {!data ? (
                <p className="mt-2 text-sm text-gray-400" data-testid="what-to-believe-unavailable" role="status">{t('research.whatToBelieve.unavailable')}</p>
            ) : data.status === 'not_applicable' ? (
                <p className="mt-2 text-sm text-gray-400" data-testid="what-to-believe-na" role="status">{t('research.whatToBelieve.notApplicable', { reason: reasonLabel(t, data.reason_code) })}</p>
            ) : (
                <>
                    {verdict ? <p className="mt-2 break-words text-sm font-medium text-gray-100" data-testid="what-to-believe-verdict">{verdict}</p> : null}
                    <p className="mt-1 text-xs text-gray-400">{t('research.whatToBelieve.subtitle')}</p>
                    <ul className="mt-3 space-y-2 text-sm text-gray-200">
                        {priceLine ? <li className="break-words" data-testid="what-to-believe-wacc">{priceLine}</li> : null}
                        {consensusLine ? <li className="break-words" data-testid="what-to-believe-consensus">{consensusLine}</li> : null}
                        {growth?.status === 'ok' && growth.required_revenue_growth !== null && growth.required_revenue_growth !== undefined ? (
                            <li className="break-words" data-testid="what-to-believe-growth">
                                {growth.current_revenue_growth !== null && growth.current_revenue_growth !== undefined
                                    ? t('research.whatToBelieve.growth', { required: f.pct(growth.required_revenue_growth), current: f.pct(growth.current_revenue_growth) })
                                    : t('research.whatToBelieve.growthNoCurrent', { required: f.pct(growth.required_revenue_growth) })}
                            </li>
                        ) : growth?.status === 'out_of_bounds' ? (
                            <li className="break-words" data-testid="what-to-believe-growth">{t('research.whatToBelieve.growthOut')}</li>
                        ) : null}
                    </ul>
                    {exit && exit.value_per_share !== null && exit.value_per_share !== undefined ? (
                        <div className="mt-3 border-t border-gray-800 pt-3" data-testid="what-to-believe-exit">
                            <h3 className="text-xs font-medium uppercase tracking-wide text-gray-500">{t('research.whatToBelieve.exitTitle')}</h3>
                            <div className="mt-2 grid grid-cols-2 gap-3 text-sm">
                                <div className="min-w-0">
                                    <p className="text-xs text-gray-500">{t('research.whatToBelieve.gordonLabel')}</p>
                                    <p className="tabular-nums text-gray-100">{exit.gordon_value_per_share !== null && exit.gordon_value_per_share !== undefined ? f.money(exit.gordon_value_per_share) : fmt.na}</p>
                                </div>
                                <div className="min-w-0">
                                    <p className="text-xs text-gray-500">{t('research.whatToBelieve.exitLabel', { multiple: multiple(exit.multiple ?? 25) })}</p>
                                    <p className="tabular-nums text-gray-100">{f.money(exit.value_per_share)}</p>
                                </div>
                            </div>
                            <p className="mt-2 text-xs text-gray-400">{t('research.whatToBelieve.exitExplain', { multiple: multiple(exit.multiple ?? 25) })}</p>
                            {exit.implied_multiple_for_price !== null && exit.implied_multiple_for_price !== undefined && data.current_price ? (
                                <p className="mt-1 text-xs text-gray-400" data-testid="what-to-believe-exit-implied">
                                    {t('research.whatToBelieve.exitImplied', { price: f.money(data.current_price), implied: multiple(exit.implied_multiple_for_price) })}
                                </p>
                            ) : null}
                        </div>
                    ) : null}
                    <p className="mt-3 text-xs text-gray-500">{t('research.whatToBelieve.explain')}</p>
                </>
            )}
        </section>
    );
}
