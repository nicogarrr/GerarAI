'use client';

import { useEffect, useState } from 'react';
import { Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import { getGems, reviewGems, type GemItem } from '@/lib/actions/propicks-gems.actions';
import { gemReasonLabel, gemReasonValue } from './gemsFormat';

export default function GemsView() {
    const t = useT();
    const locale = useLocale();
    const { formatCompanyName, formatMarketCapUsd, formatNumber, formatPercent } = useFormat();
    const [gems, setGems] = useState<GemItem[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [reviewing, setReviewing] = useState(false);
    // Resultado honesto de la última revisión: sin él, cuando la cadena LLM no
    // está disponible el botón parecía no hacer nada (cada joya volvía con un
    // discreto «Sin revisión IA» y ya).
    const [reviewStatus, setReviewStatus] = useState<string | null>(null);

    const load = async () => {
        setLoading(true);
        setError(null);
        const result = await getGems();
        if ('error' in result) setError(result.error);
        else setGems(result);
        setLoading(false);
    };

    const review = async () => {
        setReviewing(true);
        setError(null);
        setReviewStatus(null);
        const result = await reviewGems();
        if ('error' in result) {
            setError(result.error);
        } else {
            setGems(result);
            const reviewed = result.filter((gem) => gem.review_status === 'reviewed').length;
            setReviewStatus(reviewed > 0
                ? t('propicks.gems.reviewDone', { reviewed, total: result.length })
                : t('propicks.gems.reviewUnavailable'));
        }
        setReviewing(false);
    };

    useEffect(() => {
        // Carga inicial tras montar: el setState de load no es síncrono en el efecto.
        queueMicrotask(() => void load());
    }, []);

    const busy = loading || reviewing;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-lg font-bold text-gray-100">{t('propicks.gems.title')}</h3>
                <div className="flex gap-2">
                    <Button onClick={load} disabled={busy} variant="outline" className="h-11 gap-2">
                        {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="h-4 w-4" />}
                        {t('propicks.gems.refresh')}
                    </Button>
                    <Button onClick={review} disabled={busy || !gems?.length} aria-busy={reviewing} className="h-11 gap-2">
                        {reviewing ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <Sparkles aria-hidden="true" className="h-4 w-4" />}
                        {reviewing ? t('propicks.gems.reviewing') : t('propicks.gems.review')}
                    </Button>
                </div>
            </div>

            {error && (
                <Card className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-sm text-red-400">{error}</Card>
            )}

            <p aria-live="polite" role="status" className={reviewStatus ? 'text-sm text-amber-300' : 'sr-only'}>
                {reviewStatus}
            </p>

            {gems !== null && gems.length === 0 && !error && (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                    <p className="font-medium text-gray-300">{t('propicks.gems.emptyTitle')}</p>
                    <p className="mt-2 text-sm text-gray-500">
                        {t('propicks.gems.emptyDescription')}
                    </p>
                    <Button onClick={load} disabled={busy} className="mt-4 h-11 gap-2">
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        {t('propicks.gems.refresh')}
                    </Button>
                </Card>
            )}

            <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
                {(gems ?? []).map((gem) => (
                    <Card key={gem.ticker} className="min-w-0 rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-5">
                        <div className="mb-3 flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <h4 className="text-lg font-bold text-gray-100">{gem.ticker}</h4>
                                <p className="truncate text-xs text-gray-500">
                                    {formatCompanyName(gem.name)}{gem.market_cap ? ` · ${formatMarketCapUsd(gem.market_cap)}` : ''}
                                </p>
                            </div>
                            {/* La puntuación con etiqueta y escala: un número
                                suelto («73,2») no decía qué era ni sobre cuánto
                                (Tester 6). */}
                            <span className="shrink-0 rounded bg-gray-900 px-2 py-1 text-right">
                                <span className="block text-[10px] font-medium uppercase tracking-wide text-gray-500">
                                        {t('propicks.gems.score')}
                                    </span>
                                <span className="text-sm font-bold text-teal-300">
                                    {formatNumber(gem.score, { maximumFractionDigits: 1 })}
                                    <span className="text-[11px] font-medium text-teal-400/80">/100</span>
                                </span>
                            </span>
                        </div>

                        <ul className="space-y-1.5">
                            {gem.reasons.map((reason) => (
                                <li key={reason.key} className="text-sm">
                                    <div className="flex justify-between gap-3">
                                        <span className="text-gray-400">{gemReasonLabel(reason.key, locale)}</span>
                                        <span className="font-medium text-gray-100">{gemReasonValue(reason, locale)}</span>
                                    </div>
                                    <div className="text-[11px] text-gray-500">{reason.source}</div>
                                </li>
                            ))}
                        </ul>

                        {gem.review_status === 'reviewed' && (
                            <div className="mt-4 space-y-2 border-t border-gray-700 pt-3 text-sm">
                                <div className="flex items-center justify-between gap-2">
                                    <span className={gem.decision === 'veto' ? 'font-bold text-red-400' : 'font-bold text-green-400'}>
                                        {gem.decision === 'veto' ? t('propicks.gems.vetoed') : t('propicks.gems.kept')}
                                    </span>
                                    {gem.confidence !== null && gem.confidence !== undefined && (
                                        <span className="text-xs text-gray-400">{t('propicks.gems.confidence', { value: formatPercent(gem.confidence, { digits: 0 }) })}</span>
                                    )}
                                </div>
                                {gem.thesis && <p className="text-gray-300">{gem.thesis}</p>}
                                {gem.decision === 'veto' && gem.veto_reason && <p className="text-red-300">{gem.veto_reason}</p>}
                                {!!gem.risks?.length && (
                                    <ul className="list-disc space-y-1 pl-5 text-gray-400">
                                        {gem.risks.map((risk) => <li key={risk}>{risk}</li>)}
                                    </ul>
                                )}
                                {gem.invalidation && (
                                    <p className="text-xs text-gray-500">{t('propicks.gems.invalidation', { text: gem.invalidation })}</p>
                                )}
                            </div>
                        )}
                        {gem.review_status === 'sin_revision_ia' && (
                            <div className="mt-4 border-t border-gray-700 pt-3 text-xs text-amber-400">{t('propicks.gems.notReviewed')}</div>
                        )}
                    </Card>
                ))}
            </div>
        </div>
    );
}
