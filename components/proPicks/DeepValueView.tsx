'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import { getDeepValue, type DeepValueItem, type DeepValueResult } from '@/lib/actions/propicks-deep-value.actions';

/** Tope de P/B; la etiqueta («P/B ≤ 1,0» / «P/B ≤ 1.0») sigue el idioma elegido. */
const PB_OPTIONS = [0.5, 1.0, 1.5, 2.0];
/** Umbral mínimo de dividendo (0 = cualquiera); la etiqueta se compone en el idioma elegido. */
const YIELD_OPTIONS = [0, 0.03, 0.05, 0.08];



function YieldCell({ item }: { item: DeepValueItem }) {
    const t = useT();
    const { formatPercent } = useFormat();
    if (item.dividend_yield === null) {
        return <span className="text-sm text-gray-500">{t('propicks.deepValue.na')}</span>;
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold text-gray-100">
                {formatPercent(item.dividend_yield)}
            </span>
            {item.desacuerdo_fuentes && item.finnhub_yield_indicated !== null && (
                <span className="inline-flex w-fit items-center gap-1 rounded border border-amber-600/60 bg-amber-900/20 px-1.5 py-0.5 text-xs text-amber-300">
                    <AlertTriangle aria-hidden="true" className="h-3 w-3" />
                    {t('propicks.deepValue.sourcesDisagree', { value: formatPercent(item.finnhub_yield_indicated) })}
                </span>
            )}
            {item.yield_extremo_revisar && (
                <span className="inline-flex w-fit items-center gap-1 rounded border border-amber-600/60 bg-amber-900/20 px-1.5 py-0.5 text-xs text-amber-300">
                    <AlertTriangle aria-hidden="true" className="h-3 w-3" />
                    {t('propicks.deepValue.yieldExtreme')}
                </span>
            )}
        </div>
    );
}

export default function DeepValueView() {
    const t = useT();
    const locale = useLocale();
    const { formatNumber, formatPercent } = useFormat();
    const [data, setData] = useState<DeepValueResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [pbMax, setPbMax] = useState(1.0);
    const [yieldMin, setYieldMin] = useState(0);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        const result = await getDeepValue(pbMax, yieldMin);
        if ('error' in result) setError(t('propicks.deepValue.loadError'));
        else setData(result);
        setLoading(false);
    }, [pbMax, yieldMin, t]);

    useEffect(() => {
        queueMicrotask(() => void load());
    }, [load]);

    const asOf = [...(data?.resultados ?? []), ...(data?.pendientes_revision ?? [])].find((row) => row.metric_as_of)?.metric_as_of ?? null;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-lg font-bold text-gray-100">Deep value</h3>
                <Button onClick={load} disabled={loading} variant="outline" className="h-11 gap-2">
                    {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="h-4 w-4" />}
                    {t('propicks.deepValue.refresh')}
                </Button>
            </div>

            {/* Rotulo honesto de la estrategia: deep value NO es el filtro de
                calidad; el texto llega del servidor en cada respuesta. */}
            <Card role="note" className="rounded-lg border border-teal-800/60 bg-teal-950/20 p-3 text-sm text-teal-200">
                {data?.rotulo ?? t('propicks.deepValue.label')}
            </Card>

            <div className="flex flex-wrap gap-2">
                {PB_OPTIONS.map((value) => ({
                    value,
                    label: `P/B ≤ ${formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`,
                })).map((option) => (
                    <Button
                        key={option.value}
                        variant={pbMax === option.value ? 'default' : 'outline'}
                        className="h-11"
                        aria-pressed={pbMax === option.value}
                        onClick={() => setPbMax(option.value)}
                    >
                        {option.label}
                    </Button>
                ))}
                {YIELD_OPTIONS.map((value) => ({
                    value,
                    label: value === 0 ? t('propicks.deepValue.anyDividend') : t('propicks.deepValue.minDividend', { value: formatPercent(value, { digits: 0 }) }),
                })).map((option) => (
                    <Button
                        key={option.value}
                        variant={yieldMin === option.value ? 'default' : 'outline'}
                        className="h-11"
                        aria-pressed={yieldMin === option.value}
                        onClick={() => setYieldMin(option.value)}
                    >
                        {option.label}
                    </Button>
                ))}
            </div>

            {error && (
                <Card className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-sm text-red-400">{error}</Card>
            )}

            {!error && data && data.resultados.length === 0 && !(data.pendientes_revision?.length) && (
                <Card className="p-4 text-sm text-gray-400">
                    {t('propicks.deepValue.empty')}
                </Card>
            )}

            {asOf && (
                <p className="text-xs text-gray-500">{t('propicks.deepValue.asOf', { date: new Date(`${asOf}T00:00:00`).toLocaleDateString(locale === 'en' ? 'en-US' : 'es-ES', { day: 'numeric', month: 'long', year: 'numeric' }) })}</p>
            )}

            {data && <DeepValueResultSections data={data} />}
        </div>
    );
}


function DeepValueCards({ items, pending = false }: { items: DeepValueItem[]; pending?: boolean }) {
    const t = useT();
    const { formatNumber } = useFormat();
    const formatPb = (value: number) => value > 0 && value < 0.01
        ? `<${formatNumber(0.01, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}x`
        : `${formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}x`;
    return (
            <div className="grid gap-3 sm:grid-cols-2">
                {items.map((item) => (
                    <Card key={item.ticker} className="flex min-w-0 flex-col gap-2 rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                        <div className="flex items-baseline justify-between gap-2">
                            <div className="min-w-0">
                                <span className="font-bold text-teal-300">{item.ticker}</span>{' '}
                                <span className="truncate text-sm text-gray-300">{item.name}</span>
                            </div>
                            {!pending && item.score !== null && <span className="flex-none text-sm font-semibold text-gray-100">{t('propicks.deepValue.points', { value: formatNumber(item.score) })}</span>}
                        </div>
                        {pending && <p className="text-sm font-medium text-amber-300">{t('propicks.deepValue.reviewPending')}</p>}
                        {item.review_reasons?.includes('pb_split_basis_unverified') && <p className="text-xs text-amber-300">{t('propicks.deepValue.reviewSplitBasis')}</p>}
                        {item.review_reasons?.some((r) => r === 'pb_status_unverified' || r === 'pb_split_factor_invalid' || r === 'pb_inputs_inconsistent' || r === 'pb_price_stale_or_invalid') && <p className="text-xs text-amber-300">{t('propicks.deepValue.reviewPbStatus')}</p>}
                        {item.review_reasons?.includes('dividend_non_recurring') && <p className="text-xs text-amber-300">{t('propicks.deepValue.reviewNonRecurring')}</p>}
                        {item.sector && <p className="text-xs text-gray-500">{item.sector} · {item.exchange}</p>}
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <p className="text-xs text-gray-500">P/B{item.pb_fiscal_year ? ` ${t('propicks.deepValue.bookFy', { year: item.pb_fiscal_year })}` : ''}</p>
                                <p className="text-sm font-semibold text-gray-100">{formatPb(item.price_to_book)}</p>
                                {item.pb_price_date && <p className="text-xs text-gray-500">{t('propicks.deepValue.priceAsOf', { date: item.pb_price_date })}</p>}
                            </div>
                            <div>
                                <p className="text-xs text-gray-500">{t('propicks.deepValue.dividendTtm')}</p>
                                <YieldCell item={item} />
                            </div>
                        </div>
                    </Card>
                ))}
            </div>
    );
}

/** Pure result view, also used to verify the exact rendered cards offline. */
export function DeepValueResultSections({ data }: { data: DeepValueResult }) {
    const t = useT();
    // Older API payloads still contain flagged rows in resultados. Quarantine
    // them during a rolling deployment too; never display their old score.
    const needsReview = (item: DeepValueItem) => item.score === null || Boolean(
        item.desacuerdo_fuentes || item.yield_extremo_revisar || item.review_reasons?.length
    );
    const ranked = data.resultados.filter((item) => !needsReview(item));
    const pending = [...new Map([
        ...(data.pendientes_revision ?? []), ...data.resultados.filter(needsReview),
    ].map((item) => [item.ticker, item])).values()];
    return <div className="space-y-6">
        <section data-testid="deep-value-ranked" aria-label={t('propicks.deepValue.rankedTitle')}>
            {ranked.length > 0 && <h4 className="mb-3 font-semibold text-gray-100">{t('propicks.deepValue.rankedTitle')}</h4>}
            {ranked.length === 0 && pending.length > 0 && <p className="text-sm text-gray-400">{t('propicks.deepValue.noRanked')}</p>}
            <DeepValueCards items={ranked} />
        </section>
        {pending.length > 0 && <section data-testid="deep-value-review" aria-label={t('propicks.deepValue.reviewTitle')} className="space-y-3">
            <h4 className="font-semibold text-amber-300">{t('propicks.deepValue.reviewTitle')}</h4>
            <p className="text-sm text-gray-400">{t('propicks.deepValue.reviewNote')}</p>
            <DeepValueCards items={pending} pending />
        </section>}
    </div>;
}
