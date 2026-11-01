'use client';
import { useState } from 'react';
import { analystRatingEs } from '@/lib/research/analyst-rating-es';
import type { components } from '@/lib/research/openapi.generated';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
type AnalystTargets = components['schemas']['AnalystTargets'];
export function AnalystTargetsView({data,currency}:{data:AnalystTargets|null;currency?:string|null}) {
    // Only this response can declare the unit of its target prices. The
    // company master may use a different scale (e.g. GBP versus GBX).
    const t = useT();
    const fmt = useFormat();
    const locale = useLocale();
    const [page, setPage] = useState(0);
    const count = data?.rows.length ?? 0;
    const pages = Math.max(1, Math.ceil(count / 5));
    const current = Math.min(page, pages - 1);
    const rows = data?.rows.slice(current * 5, (current + 1) * 5) ?? [];
    const cur = data?.currency?.trim() || null;
    const fmtTarget = (value: number | null | undefined) =>
        value === null || value === undefined
            ? fmt.na
            : cur
              ? fmt.formatPrice(value, cur)
              : fmt.formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (
        <section aria-labelledby="analyst-targets-title" className="rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="analyst-targets">
            <h2 className="sr-only text-base font-semibold text-gray-100 md:not-sr-only" id="analyst-targets-title">{t('research.analystTargets.title')}</h2>
            {!data || data.status === 'unavailable' ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{data?.note ?? t('research.analystTargets.unavailable')}</p>
            ) : data.rows.length === 0 && !data.consensus ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{data.note ?? t('research.analystTargets.empty')}</p>
            ) : (
                <>
                    {!cur ? <p className="mt-2 text-xs text-gray-400">{t('research.analystTargets.currencyUndeclared')}</p> : null}
                    {cur && currency && cur.toUpperCase() !== currency.trim().toUpperCase() ? (
                        <p className="mt-2 text-xs text-gray-400" data-testid="analyst-targets-currency-note">
                            {cur.toUpperCase() === 'USD' ? t('research.analystTargets.currencyAdr', { currency: currency.trim().toUpperCase() }) : t('research.analystTargets.currencyOther', { target: cur.toUpperCase(), currency: currency.trim().toUpperCase() })}
                        </p>
                    ) : null}
                    {data.consensus ? (
                        <div className="mt-1 text-sm text-gray-300">
                            <p>
                                {t('research.analystTargets.consensus', { median: fmtTarget(data.consensus.median), mean: fmtTarget(data.consensus.mean), low: fmtTarget(data.consensus.low), high: fmtTarget(data.consensus.high) })}
                            </p>

                        </div>
                    ) : null}
                    {data.rows.length === 0 ? (
                        <p className="mt-2 text-sm text-gray-400" role="status">{data.note ?? t('research.analystTargets.consensusOnly')}</p>
                    ) : null}
                    {data.rows.length > 0 ? (
                    <>
                    {pages > 1 ? <nav aria-label={t('research.analystTargets.paginationAria')} className="mt-3 flex items-center justify-between gap-2 text-xs text-gray-300">
                      <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current === 0} onClick={() => setPage(current - 1)}>{t('research.analystTargets.previous')}</button>
                      <span aria-live="polite"><span className="whitespace-nowrap">{t('research.pageOf', { current: current + 1, total: pages })}</span> · {t('research.analystTargets.firms', { count })}</span>
                      <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>{t('research.analystTargets.next')}</button>
                    </nav> : null}
                    <ul aria-label={t('research.analystTargets.listAria')} className="mt-1 divide-y divide-gray-800 sm:hidden">
                        {rows.map((row) => (
                            <li className="py-2 text-sm" key={`${row.firm}-${row.date}`}>
                                <div className="flex items-baseline justify-between gap-3">
                                    <span className="min-w-0 font-medium text-gray-100">{row.firm}</span>
                                    <span className="shrink-0 tabular-nums text-gray-100">{fmtTarget(row.price_target)}</span>
                                </div>
                                <div className="mt-0.5 flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-gray-400">
                                    <span>{analystRatingEs(row.rating, locale) ?? fmt.na} · {fmt.formatMarketDate(row.date)}</span>
                                    <span className="tabular-nums">{t('research.analystTargets.priorLabel', { value: fmtTarget(row.prior_target) })} · <span title={t('research.analystTargets.upsideTitle')}>{t('research.analystTargets.upside')}</span> {!cur || row.upside_percent === null || row.upside_percent === undefined ? fmt.na : fmt.formatPercent(row.upside_percent, { fromRatio: false, signDisplay: 'always' })}</span>
                                </div>
                            </li>
                        ))}
                    </ul>
                    <div className="mt-1 hidden overflow-x-auto sm:block">
                        <table className="w-full min-w-[34rem] text-left text-sm">
                            <caption className="sr-only">{t('research.analystTargets.caption')}</caption>
                            <thead className="text-xs text-gray-500">
                                <tr>
                                    <th className="py-1.5 pr-3 font-medium" scope="col">{t('research.analystTargets.colFirm')}</th>
                                    <th className="py-1.5 pr-3 font-medium" scope="col">{t('research.analystTargets.colRating')}</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">{t('research.analystTargets.colTarget')}</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">{t('research.analystTargets.colPrior')}</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col" title={t('research.analystTargets.upsideTitle')}>{t('research.analystTargets.upside')}</th>
                                    <th className="py-1.5 font-medium" scope="col">{t('research.analystTargets.colDate')}</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {rows.map((row) => (
                                    <tr key={`${row.firm}-${row.date}`}>
                                        <th className="py-1.5 pr-3 font-medium text-gray-100" scope="row">{row.firm}</th>
                                        <td className="py-1.5 pr-3 text-gray-300">{analystRatingEs(row.rating, locale) ?? fmt.na}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-100">{fmtTarget(row.price_target)}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-400">{fmtTarget(row.prior_target)}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-300">{!cur || row.upside_percent === null || row.upside_percent === undefined ? fmt.na : fmt.formatPercent(row.upside_percent, { fromRatio: false, signDisplay: 'always' })}</td>
                                        <td className="py-1.5 text-gray-400">{fmt.formatMarketDate(row.date)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    </>
                    ) : null}
                    <p className="mt-2 text-xs text-gray-500">
                        {t('research.analystTargets.fetched', { date: fmt.formatUserDateTime(data.fetched_at * 1000) })}
                        {cur && data.reference_price ? t('research.analystTargets.upsideVs', { price: fmtTarget(data.reference_price), source: data.reference_price_source ?? t('research.analystTargets.referencePrice') }) : t('research.analystTargets.noReference')}
                        {t('research.analystTargets.thirdParty')}
                    </p>
                </>
            )}
        </section>
    );
}
