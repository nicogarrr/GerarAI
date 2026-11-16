import Link from 'next/link';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { getWatchlistNew13f } from '@/lib/actions/watchlist-new-13f.actions';
import { mapNewPositions } from '@/lib/watchlist/new-13f';
import New13fSummary from './New13fSummary';

export default async function New13fSection({ promise, t }: {
    promise: ReturnType<typeof getWatchlistNew13f>;
    t: TranslateFn;
}) {
    const result = await promise;
    const rows = (result.data ?? []).map(item => mapNewPositions(item.ticker, item));
    if (!result.unavailable && rows.length === 0) return null;
    return <section className="rounded-xl border border-gray-700/60 bg-gray-900/60 p-4">
        <h2 className="text-sm font-semibold text-gray-200">{t('watchlist.new13f.title')}</h2>
        {result.unavailable ? <p role="status" className="mt-2 text-xs text-gray-400">{t('watchlist.new13f.unavailable')}</p> : (
            <ul className="mt-2 space-y-2">
                {rows.map(row => <li key={row.ticker} className="flex min-w-0 items-baseline gap-3">
                    <Link href={`/research/${encodeURIComponent(row.ticker)}`} className="shrink-0 font-mono text-sm font-bold text-gray-200">{row.ticker}</Link>
                    <New13fSummary data={row} />
                </li>)}
            </ul>
        )}
    </section>;
}
