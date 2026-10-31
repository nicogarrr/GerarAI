'use client';

import type { PortfolioDataQuality } from '@/lib/actions/portfolio.actions';
import { useT, useFormat } from '@/lib/i18n/client';

export default function PortfolioDataNotice({ quality }: { quality?: PortfolioDataQuality | null }) {
    const ti = useT();
    const f = useFormat();
    if (!quality || quality.status === 'no_portfolio') return null;
    return (
        <div className="mb-4 rounded-lg border border-gray-700 bg-gray-900/40 p-3 text-sm text-gray-400" role="note">
            {quality.missing_cost_positions > 0 && <p className="mt-2 text-amber-300">
                {ti('portfolio.dataNotice.missingCostPrefix', { count: quality.missing_cost_positions === 1 ? ti('portfolio.dataNotice.positionOne') : ti('portfolio.dataNotice.positionMany', { n: quality.missing_cost_positions }) })}
                {quality.position_sources.includes('ibkr_flex') ? ti('portfolio.dataNotice.missingCostIbkr') : ti('portfolio.dataNotice.missingCostManual')}
                {ti('portfolio.dataNotice.missingCostSuffix')}
            </p>}
            {quality.position_sources.includes('screenshot_confirmed') && <p className="mt-2 text-amber-300">
                {ti('portfolio.dataNotice.screenshotLine1')}
                {ti('portfolio.dataNotice.screenshotLine2')}
                {ti('portfolio.dataNotice.screenshotLine3')}
            </p>}
            <details className="mt-2">
                <summary className="cursor-pointer">{ti('portfolio.dataNotice.detailsSummary')}</summary>
                <p className="mt-2">{ti('portfolio.dataNotice.datesLine', {
                        positionDates: quality.position_dates.map((d) => f.formatDate(d)).join(', ') || ti('portfolio.dataNotice.dateUnavailable'),
                        cashDates: quality.cash_dates.map((d) => f.formatDate(d)).join(', ') || ti('portfolio.dataNotice.dateUnavailable'),
                    })}</p>
                <p className="mt-2">{ti('portfolio.dataNotice.cashLine', {
                        balances: Object.entries(quality.cash_native).map(([currency, balance]) => f.formatMoney(balance, currency)).join(' · ') || ti('portfolio.dataNotice.noBalances'),
                    })}</p>
                <p className="mt-2">{ti('portfolio.dataNotice.snapshotsLine', { snapshots: quality.snapshots, complete: quality.complete_snapshots, returns: quality.return_observations })}</p>
            </details>
        </div>
    );
}
