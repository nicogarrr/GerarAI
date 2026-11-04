'use client';
import { useState } from 'react';
import type { AnalystFirmScore, AnalystHistory, AnalystHistoryHorizon } from '@/lib/research/analyst-history';
import { useFormat, useT } from '@/lib/i18n/client';

type Horizon = AnalystHistoryHorizon['horizon'];

function FirmList({ firms, title, testId }: { firms: AnalystFirmScore[]; title: string; testId: string }) {
    const t = useT();
    const fmt = useFormat();
    if (firms.length === 0) return null;
    const pct = (value: number) => fmt.formatPercent(value, { fromRatio: false, digits: 0 });
    return (
        <div className="min-w-0" data-testid={testId}>
            <h3 className="text-xs font-medium uppercase tracking-wide text-gray-500">{title}</h3>
            <ol className="mt-1 divide-y divide-gray-800">
                {firms.map((firm) => (
                    <li className="min-w-0 py-1.5" key={firm.firm}>
                        <div className="flex items-baseline justify-between gap-3">
                            <span className="min-w-0 break-words text-sm font-medium text-gray-100">{firm.firm}</span>
                            {firm.relative_error !== null && firm.relative_error !== undefined ? (
                                <span className="shrink-0 text-xs tabular-nums text-gray-400" title={t('research.analystHistory.relativeTitle')}>
                                    {t('research.analystHistory.relative', { value: fmt.formatNumber(firm.relative_error, { maximumFractionDigits: 1, signDisplay: 'always' }) })}
                                </span>
                            ) : null}
                        </div>
                        <p className="mt-0.5 text-xs tabular-nums text-gray-400">
                            {t('research.analystHistory.firmLine', { count: firm.samples, error: pct(firm.median_abs_error_pct), hit: pct(firm.direction_hit_rate * 100) })}
                        </p>
                    </li>
                ))}
            </ol>
        </div>
    );
}

export function AnalystHistorySkeleton() {
    const t = useT();
    return (
        <section aria-busy="true" className="rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="analyst-history-loading">
            <p className="text-sm text-gray-400" role="status">{t('research.analystHistory.loading')}</p>
            <div aria-hidden="true" className="mt-3 space-y-2">
                <div className="h-3 w-2/3 animate-pulse rounded bg-gray-800" />
                <div className="h-3 w-1/2 animate-pulse rounded bg-gray-800" />
            </div>
        </section>
    );
}

export function AnalystHistoryView({ data }: { data: AnalystHistory | null }) {
    const t = useT();
    const fmt = useFormat();
    const [chosen, setChosen] = useState<Horizon | null>(null);
    const horizons = data?.horizons ?? [];
    const best = data?.best_horizon ?? null;
    const active = horizons.find((h) => h.horizon === (chosen ?? best ?? '12m')) ?? horizons[horizons.length - 1] ?? null;
    const cur = data?.currency?.trim() || null;
    const money = (value: number) => (cur ? fmt.formatPrice(value, cur) : fmt.formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    const pct = (value: number | null | undefined) =>
        value === null || value === undefined ? fmt.na : fmt.formatPercent(value, { fromRatio: false, digits: 0 });
    const horizonLabel = (h: Horizon) => (h === '6m' ? t('research.analystHistory.horizon6m') : t('research.analystHistory.horizon12m'));
    const emptyText =
        data?.note_code === 'not_equity' ? t('research.analystHistory.notEquity') : t('research.analystHistory.empty');
    const bestSummary = horizons.find((h) => h.horizon === best);
    const changes = data?.rating_changes;
    return (
        <section aria-labelledby="analyst-history-title" className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="analyst-history">
            <h2 className="sr-only text-base font-semibold text-gray-100 md:not-sr-only" id="analyst-history-title">{t('research.analystHistory.title')}</h2>
            {!data || data.status === 'unavailable' ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{t('research.analystHistory.unavailable')}</p>
            ) : data.status === 'empty' ? (
                <p className="mt-2 text-sm text-gray-400" data-testid="analyst-history-empty" role="status">{emptyText}</p>
            ) : (
                <>
                    <p className="mt-1 text-xs text-gray-400">{t('research.analystHistory.subtitle')}</p>
                    {data.note_code === 'no_matured' || !active ? (
                        <p className="mt-2 text-sm text-gray-400" role="status">{t('research.analystHistory.noMatured')}</p>
                    ) : (
                        <>
                            <div aria-label={t('research.analystHistory.horizonAria')} className="mt-3 flex flex-wrap gap-2" role="group">
                                {horizons.map((h) => (
                                    <button
                                        aria-pressed={h.horizon === active.horizon}
                                        className={`min-h-[44px] rounded-lg border px-3 text-sm ${h.horizon === active.horizon ? 'border-gray-500 bg-gray-800 text-gray-100' : 'border-gray-800 text-gray-400 hover:text-gray-200'}`}
                                        key={h.horizon}
                                        onClick={() => setChosen(h.horizon)}
                                        type="button"
                                    >
                                        {horizonLabel(h.horizon)}
                                        {h.horizon === best ? <span className="ml-1.5 rounded bg-gray-700 px-1.5 py-0.5 text-[11px] text-gray-200">{t('research.analystHistory.bestBadge')}</span> : null}
                                    </button>
                                ))}
                            </div>
                            <p className="mt-2 text-xs text-gray-400" data-testid="analyst-history-best">
                                {best && bestSummary
                                    ? t('research.analystHistory.bestHorizon', { horizon: horizonLabel(best), error: pct(bestSummary.median_abs_error_pct) })
                                    : t('research.analystHistory.noBestHorizon')}
                            </p>
                            <p className="mt-2 text-sm tabular-nums text-gray-300">
                                {t('research.analystHistory.summary', { count: active.matured_targets, error: pct(active.median_abs_error_pct), hit: pct(active.direction_hit_rate === null || active.direction_hit_rate === undefined ? null : active.direction_hit_rate * 100) })}
                            </p>
                            {(active.ranked_firms ?? 0) === 0 ? (
                                <p className="mt-2 text-sm text-gray-400" data-testid="analyst-history-no-ranked">{t('research.analystHistory.noRanked', { min: data.min_samples ?? 5 })}</p>
                            ) : (
                                <div className="mt-3 grid min-w-0 gap-4 sm:grid-cols-2">
                                    <FirmList firms={active.top ?? []} testId="analyst-history-top" title={t('research.analystHistory.topTitle')} />
                                    <FirmList firms={active.bottom ?? []} testId="analyst-history-bottom" title={t('research.analystHistory.bottomTitle')} />
                                </div>
                            )}
                            {(active.small_sample_firms ?? 0) > 0 ? (
                                <p className="mt-2 text-xs text-gray-500" data-testid="analyst-history-small-sample">{t('research.analystHistory.smallSample', { count: active.small_sample_firms ?? 0, min: data.min_samples ?? 5 })}</p>
                            ) : null}
                        </>
                    )}
                    {data.consensus ? (
                        <div className="mt-3 border-t border-gray-800 pt-3 text-sm text-gray-300" data-testid="analyst-history-consensus">
                            <p>
                                {t('research.analystHistory.consensus', { mean: money(data.consensus.mean), firms: data.consensus.firms })}
                                {data.consensus.upside_percent !== null && data.consensus.upside_percent !== undefined && data.consensus.reference_price
                                    ? ` · ${t('research.analystHistory.consensusUpside', { upside: fmt.formatPercent(data.consensus.upside_percent, { fromRatio: false, signDisplay: 'always' }), price: money(data.consensus.reference_price) })}`
                                    : null}
                            </p>
                            <p className="mt-1 text-xs text-gray-500">{t('research.analystHistory.consensusWhy')}</p>
                        </div>
                    ) : null}
                    {changes && (changes.upgrades ?? 0) + (changes.downgrades ?? 0) > 0 ? (
                        <p className="mt-2 text-xs text-gray-400" data-testid="analyst-history-rating-note">
                            {t('research.analystHistory.ratingChanges', { days: changes.window_days ?? 90, up: changes.upgrades ?? 0, down: changes.downgrades ?? 0 })} {t('research.analystHistory.contrarianNote')}
                        </p>
                    ) : null}
                    <p className="mt-2 break-words text-xs text-gray-500">
                        {t('research.analystHistory.footer', { source: data.source ?? 'Yahoo Finance', date: fmt.formatUserDateTime(data.fetched_at * 1000) })}
                    </p>
                </>
            )}
        </section>
    );
}
