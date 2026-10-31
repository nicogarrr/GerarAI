'use client';

import { useState } from 'react';
import type { HistoricalStressReport, StressWindow } from '@/types/historical-stress';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';

type StressReasonKey =
    | 'history_gaps'
    | 'provider_error'
    | 'no_safe_symbol'
    | 'currency_mismatch'
    | 'currency_unverified'
    | 'incomplete_portfolio';

const REASON_LABEL_KEYS: Record<StressReasonKey, string> = {
    history_gaps: 'portfolio.stress.reason_history_gaps',
    provider_error: 'portfolio.stress.reason_provider_error',
    no_safe_symbol: 'portfolio.stress.reason_no_safe_symbol',
    currency_mismatch: 'portfolio.stress.reason_currency_mismatch',
    currency_unverified: 'portfolio.stress.reason_currency_unverified',
    incomplete_portfolio: 'portfolio.stress.reason_incomplete_portfolio',
};
const REASON_KEYS = Object.keys(REASON_LABEL_KEYS) as StressReasonKey[];

function WindowCard({ window, ti, f }: { window: StressWindow; ti: TFunction; f: Formatters }) {
    const day = (value?: string | null) => (value ? f.formatMarketDate(value) : ti('portfolio.stress.noData'));
    const reasonKey: StressReasonKey = REASON_KEYS.includes(window.reason as StressReasonKey)
        ? (window.reason as StressReasonKey)
        : 'incomplete_portfolio';
    return <article className="rounded-xl border border-gray-800 bg-surface-1 p-4">
        <h3 className="text-xl font-semibold text-gray-100">{window.year}</h3>
        {window.status === 'SIN_DATOS' ? <div className="mt-3 text-sm text-amber-300">
            <p>{ti('common.na')}</p><p className="mt-1 text-gray-400">{ti(REASON_LABEL_KEYS[reasonKey] as Parameters<TFunction>[0])}</p>
            {window.missing_tickers?.length ? <p className="mt-2 break-words">{ti('portfolio.stress.noHistoryFor', { tickers: window.missing_tickers.join(', ') })}</p> : null}
        </div> : <>
            <dl className="mt-3 space-y-3 text-sm">
                <div className="flex justify-between gap-2"><dt className="text-gray-400">{ti('portfolio.stress.yearReturn')}</dt><dd>{f.formatPercent(window.return)}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-gray-400">{ti('portfolio.stress.maxDrawdown')}</dt><dd className="text-red-300">{f.formatPercent(window.max_drawdown)}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-gray-400">{ti('portfolio.stress.peakTrough')}</dt><dd className="text-right">{day(window.peak_date)}<br />{day(window.trough_date)}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-gray-400">{ti('portfolio.stress.recoveryFromPeak')}</dt><dd className="text-right"><span className="whitespace-nowrap">{window.recovery_date ? ti('portfolio.stress.recoveryDays', { days: window.recovery_days ?? '' }) : window.recovery_status === 'history_gaps' ? ti('portfolio.stress.recoveryUnverified') : ti('portfolio.stress.recoveryNone')}</span><br /><span className="whitespace-nowrap">{window.recovery_date ? day(window.recovery_date) : ti('portfolio.stress.recoveryUntil', { date: day(window.last_observation) })}</span></dd></div>
            </dl>
            <p className="mt-4 border-t border-gray-800 pt-3 text-xs text-gray-500">{ti('portfolio.stress.rangeSessions', {
                start: day(window.start_date),
                end: day(window.end_date),
                sessions: typeof window.observations === 'number'
                    ? window.observations === 1 ? ti('portfolio.stress.sessionOne') : ti('portfolio.stress.sessionMany', { n: window.observations })
                    : ti('portfolio.stress.sessionsUnavailable'),
            })}</p>
        </>}
    </article>;
}

export default function HistoricalStressView({ report }: { report: HistoricalStressReport }) {
    const ti = useT();
    const f = useFormat();
    const day = (value?: string | null) => (value ? f.formatMarketDate(value) : ti('portfolio.stress.noData'));
    const [page, setPage] = useState(0);
    const size = 5;
    const pages = Math.ceil(report.companies.length / size);
    return <div className="space-y-6">
        {report.mode === 'portfolio' && <section aria-label={ti('portfolio.stress.portfolioLabel')}>
            <h2 className="mb-3 font-semibold text-gray-100">{ti('portfolio.stress.currentPortfolio')}</h2>
            <p className="mb-4 text-sm text-gray-400">{ti('portfolio.stress.portfolioNote')}</p>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{report.portfolio.map(window => <WindowCard key={window.year} window={window} ti={ti} f={f} />)}</div>
        </section>}
        {report.companies.length === 0 && <p className="rounded-xl border border-gray-800 p-5 text-gray-400">{ti('portfolio.stress.noPositions')}</p>}
        {report.companies.slice(page * size, (page + 1) * size).map(company => <section key={company.ticker} aria-label={company.ticker}>
            <h2 className="mb-3 font-semibold text-teal-300">{company.ticker}{company.weight !== null ? ti('portfolio.stress.weightSuffix', { weight: f.formatPercent(company.weight) }) : ''}</h2>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{company.windows.map(window => <WindowCard key={window.year} window={window} ti={ti} f={f} />)}</div>
            <p className="mt-2 text-xs text-gray-500">
                {company.source_url ? <a className="inline-flex min-h-11 min-w-11 items-center text-teal-300 underline" href={company.source_url} target="_blank" rel="noopener noreferrer">{company.source}</a> : company.source} · {ti('portfolio.stress.adjustedClose')} · {company.currency ?? ti('portfolio.stress.currencyNoData')} · {ti('portfolio.stress.fetched', { date: day(company.fetched_at) })}
                {company.weight_as_of ? ti('portfolio.stress.weightAsOf', { date: day(company.weight_as_of) }) : ''}
            </p>
        </section>)}
        {pages > 1 && <nav aria-label={ti('portfolio.stress.paginationLabel')} className="flex items-center justify-between gap-3 text-sm">
            <button className="min-h-11 min-w-11 rounded border border-gray-700 px-3 py-2 disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>{ti('portfolio.stress.previous')}</button>
            <span>{page + 1} / {pages}</span>
            <button className="min-h-11 min-w-11 rounded border border-gray-700 px-3 py-2 disabled:opacity-40" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>{ti('portfolio.stress.next')}</button>
        </nav>}
        <details className="rounded-xl border border-gray-800 p-4 text-sm text-gray-400"><summary className="min-h-11 cursor-pointer py-3">{ti('portfolio.stress.methodTitle')}</summary>
            <p className="mt-3">{ti('portfolio.stress.methodWindows')}</p>
            <p className="mt-2">{ti('portfolio.stress.methodLimits')}</p>
        </details>
    </div>;
}
