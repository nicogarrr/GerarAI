'use client';

import { useFormat, useT } from '@/lib/i18n/client';
import type { WatchlistNew13f } from '@/lib/watchlist/new-13f';

interface New13fSummaryProps {
    data: WatchlistNew13f;
}

/** Resumen de las nuevas posiciones institucionales (13F) de una empresa de la
    watchlist: cuántas son nuevas este trimestre, las mayores y su total.
    Ausencia declarada («Sin datos» / conteo sin detalle), nunca cifras
    inventadas; el valor es el declarado al cierre del trimestre o N/D. */
export default function New13fSummary({ data }: New13fSummaryProps) {
    const t = useT();
    const { formatNumber, formatMoneyCompact, na: NA } = useFormat();

    if (data.status === 'no_data' || data.countNew === null) {
        return <span className="text-xs text-gray-500">{t('watchlist.new13f.noData')}</span>;
    }

    const count = data.countNew;
    return (
        <div className="min-w-0" data-testid="new-13f-summary">
            <p className="text-xs text-gray-300">
                {t(count === 1 ? 'watchlist.new13f.countQuarterOne' : 'watchlist.new13f.countQuarter', { count, period: data.period ?? NA })}
            </p>
            {data.status === 'count_only' ? (
                <p className="text-xs text-gray-500">{t('watchlist.new13f.countOnly')}</p>
            ) : data.topNew.length > 0 ? (
                <>
                    <ul className="mt-1 space-y-0.5">
                        {data.topNew.map((row) => (
                            <li key={row.id} className="flex min-w-0 items-baseline gap-2 text-xs">
                                <span className="min-w-0 truncate text-gray-200" title={row.fund}>{row.fund}</span>
                                <span className="shrink-0 font-mono text-gray-400">
                                    {formatNumber(row.shares, { maximumFractionDigits: 0 })} {t('watchlist.new13f.sharesSuffix')}
                                </span>
                                <span
                                    className="shrink-0 font-mono text-gray-500"
                                    title={row.valueApprox === null ? undefined : t('watchlist.new13f.valueDeclaredTitle')}
                                >
                                    {row.valueApprox === null ? NA : formatMoneyCompact(row.valueApprox, 'USD', { maximumFractionDigits: 1 })}
                                </span>
                            </li>
                        ))}
                    </ul>
                    <p className="mt-1 text-xs text-gray-500">
                        {t('watchlist.new13f.topTotal', { shares: formatNumber(data.topTotalShares, { maximumFractionDigits: 0 }) })}
                        {data.partial ? ` · ${t('watchlist.new13f.partial')}` : ''}
                    </p>
                </>
            ) : null}
        </div>
    );
}
