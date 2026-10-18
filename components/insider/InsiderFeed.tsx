import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { formatDate, formatMoney, formatNumber } from '@/lib/format';
import type { InsiderFeedResult } from '@/lib/actions/insider.actions';
import { insiderName, insiderRole, sideLabel } from '@/lib/insider/format';

const SIDES = [
    ['all', 'Todas'],
    ['buy', 'Compras'],
    ['sell', 'Ventas'],
] as const;
const PERIODS = [
    [30, '30 días'],
    [90, '90 días'],
    [365, '1 año'],
] as const;

const usd = (value: number | null | undefined, digits = 0) =>
    typeof value === 'number' && Number.isFinite(value) ? formatMoney(value, 'USD', { maximumFractionDigits: digits }) : '—';

function href(side: string, days: number) {
    const params = new URLSearchParams();
    if (side !== 'all') params.set('lado', side);
    if (days !== 90) params.set('dias', String(days));
    const query = params.toString();
    return query ? `/insider?${query}` : '/insider';
}

function Filter<T extends string | number>({
    options,
    current,
    build,
    label,
}: {
    options: readonly (readonly [T, string])[];
    current: T;
    build: (value: T) => string;
    label: string;
}) {
    return (
        <nav aria-label={label} className="flex gap-1">
            {options.map(([value, text]) => (
                <Link
                    aria-current={value === current ? 'page' : undefined}
                    className={`inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium ${value === current ? 'bg-teal-400/10 text-teal-300' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'}`}
                    href={build(value)}
                    key={String(value)}
                >
                    {text}
                </Link>
            ))}
        </nav>
    );
}

export default function InsiderFeed({ feed, side, days }: { feed: InsiderFeedResult | null; side: string; days: number }) {
    if (!feed || feed.status !== 'ok') {
        return (
            <section className="rounded-xl border border-gray-800 bg-surface-1 p-5 text-sm text-gray-400">
                No se pudo leer el histórico insider. Reintenta en unos minutos.
            </section>
        );
    }
    const totals = feed.totals;
    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Filter build={(value) => href(value, days)} current={side as 'all' | 'buy' | 'sell'} label="Lado" options={SIDES} />
                <Filter build={(value) => href(side, value)} current={days as 30 | 90 | 365} label="Periodo" options={PERIODS} />
            </div>

            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[
                    ['Compras', `${formatNumber(totals.buy_count, { maximumFractionDigits: 0 })} · ${usd(totals.buy_value)}`],
                    ['Ventas', `${formatNumber(totals.sell_count, { maximumFractionDigits: 0 })} · ${usd(totals.sell_value)}`],
                    ['Clusters', formatNumber(feed.clusters.length, { maximumFractionDigits: 0 })],
                    ['Compras CEO/CFO', formatNumber(feed.c_suite_buys.length, { maximumFractionDigits: 0 })],
                ].map(([label, value]) => (
                    <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={label}>
                        <dt className="text-xs text-gray-500">{label}</dt>
                        <dd className="mt-1 text-xl font-bold tabular-nums text-gray-100">{value}</dd>
                    </div>
                ))}
            </dl>

            {feed.clusters.length > 0 ? (
                <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                    <h2 className="text-sm font-semibold text-gray-100">Clusters de compra</h2>
                    <ul className="mt-3 divide-y divide-gray-900 text-sm">
                        {feed.clusters.map((cluster) => (
                            <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2" key={`${cluster.ticker}-${cluster.window_start}`}>
                                <Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/insider?ticker=${cluster.ticker}`}>
                                    {cluster.ticker}
                                </Link>
                                <span className="text-gray-300">{cluster.insider_count} insiders</span>
                                <span className="tabular-nums text-gray-300">{usd(cluster.total_value)}</span>
                                <span className="text-gray-500">desde {formatDate(cluster.window_start)}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}

            {feed.c_suite_buys.length > 0 ? (
                <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                    <h2 className="text-sm font-semibold text-gray-100">Compras de CEO y CFO</h2>
                    <ul className="mt-3 divide-y divide-gray-900 text-sm">
                        {feed.c_suite_buys.map((buy) => (
                            <li
                                className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
                                key={`${buy.accession_number}-${buy.tx_line}`}
                            >
                                <Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/insider?ticker=${buy.ticker}`}>
                                    {buy.ticker}
                                </Link>
                                <span className="text-gray-100">{insiderName(buy.insider)}</span>
                                <span className="text-gray-400">{insiderRole(buy.role, buy.officer_title)}</span>
                                <span className="tabular-nums text-gray-300">{usd(buy.value)}</span>
                                <span className="text-gray-500">{buy.date ? formatDate(buy.date) : '—'}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}

            <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                <h2 className="text-sm font-semibold text-gray-100">Operaciones</h2>
                {feed.transactions.length === 0 ? (
                    <p className="mt-3 text-sm text-gray-500">Sin operaciones en este periodo.</p>
                ) : (
                    <div className="mt-3 overflow-x-auto">
                        <table className="w-full min-w-[720px] text-left text-sm">
                            <thead className="text-xs uppercase text-gray-500">
                                <tr>
                                    <th className="py-1 pr-3 font-medium" scope="col">Fecha</th>
                                    <th className="px-3 py-1 font-medium" scope="col">Ticker</th>
                                    <th className="px-3 py-1 font-medium" scope="col">Insider</th>
                                    <th className="px-3 py-1 font-medium" scope="col">Cargo</th>
                                    <th className="px-3 py-1 font-medium" scope="col">Operación</th>
                                    <th className="px-3 py-1 text-right font-medium" scope="col">Acciones</th>
                                    <th className="px-3 py-1 text-right font-medium" scope="col">Precio</th>
                                    <th className="py-1 pl-3 text-right font-medium" scope="col">Importe</th>
                                </tr>
                            </thead>
                            <tbody>
                                {feed.transactions.map((tx, index) => (
                                    <tr className="border-t border-gray-900" key={`${tx.accession_number}-${index}`}>
                                        <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-gray-400">{tx.date ? formatDate(tx.date) : '—'}</td>
                                        <td className="px-3 py-2 font-semibold">
                                            <Link className="text-teal-300 hover:text-teal-200" href={`/insider?ticker=${tx.ticker}`}>
                                                {tx.ticker}
                                            </Link>
                                        </td>
                                        <td className="px-3 py-2 text-gray-100">{insiderName(tx.insider)}</td>
                                        <td className="px-3 py-2 text-gray-400">{insiderRole(tx.role, tx.officer_title)}</td>
                                        <td className={`px-3 py-2 font-medium ${tx.side === 'compra' ? 'text-teal-300' : 'text-red-400'}`}>{sideLabel(tx.side)}</td>
                                        <td className="px-3 py-2 text-right tabular-nums">{formatNumber(tx.shares ?? null, { maximumFractionDigits: 0 })}</td>
                                        <td className="px-3 py-2 text-right tabular-nums">{usd(tx.price, 2)}</td>
                                        <td className="py-2 pl-3 text-right tabular-nums">
                                            {tx.source_url ? (
                                                <a
                                                    className="inline-flex items-center gap-1 text-gray-100 hover:text-teal-300"
                                                    href={tx.source_url}
                                                    rel="noopener noreferrer"
                                                    target="_blank"
                                                >
                                                    {usd(tx.value)}
                                                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                                                </a>
                                            ) : (
                                                usd(tx.value)
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
}
