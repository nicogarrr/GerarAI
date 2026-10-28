import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { formatDate, formatMarketCapUsd, formatNumber, formatPrice, isValidCurrencyCode } from '@/lib/format';
import type { InsiderFeedResult, InsiderFeedSignal, InsiderFeedTransaction } from '@/lib/actions/insider.actions';
import { insiderName, insiderRole, isInstitutionalInsiderName, sideLabel } from '@/lib/insider/format';

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

// La divisa es por operacion y siempre declarada (SEC = USD, PDMR UK = GBP);
// nunca se asume una ni se mezclan en un solo formato.
const usd = (value: number | null | undefined, digits = 0, currency?: string) =>
    typeof value === 'number' && Number.isFinite(value)
        ? currency
            ? formatPrice(value, currency, { minimumFractionDigits: digits, maximumFractionDigits: digits })
            : formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })
        : '—';
// El backend declara la divisa por operacion (SEC Form 4 = USD; PDMR UK = la
// que informe la fuente: GBP/USD/EUR... y 93/307 llegan sin informar). Si
// falta: numero sin simbolo + "divisa no informada", nunca se asume.
const txCurrency = (tx: InsiderFeedTransaction) => (tx.currency && isValidCurrencyCode(tx.currency) ? tx.currency : undefined);

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

/** Fila de señal (cluster / CEO-CFO / gran compra): ticker, quién, cuánto y cuándo. */
function SignalLine({ signal, children }: { signal: InsiderFeedSignal; children?: React.ReactNode }) {
    return (
        <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
            <Link className="inline-flex min-h-11 min-w-11 items-center font-semibold text-teal-300 hover:text-teal-200" href={`/insider?ticker=${signal.ticker}`}>
                {signal.ticker}
            </Link>
            {signal.insider ? <span className="text-gray-100">{insiderName(signal.insider)}</span> : null}
            {signal.role || signal.officer_title ? (
                <span className="text-gray-400">{insiderRole(signal.role, signal.officer_title)}</span>
            ) : null}
            {isInstitutionalInsiderName(signal.insider) ? (
                <span className="rounded-full bg-indigo-950/60 px-2 py-0.5 text-xs font-semibold text-indigo-300">Institucional</span>
            ) : null}
            {children}
            <span className="tabular-nums text-gray-300">{usd(signal.value ?? signal.total_value, 0, 'USD')}</span>
            <span className="text-gray-500">{signal.date ? formatDate(signal.date) : signal.window_start ? `desde ${formatDate(signal.window_start)}` : '—'}</span>
        </li>
    );
}

function trancheNote(tranches: number | undefined): string | null {
    return tranches && tranches > 1 ? `${formatNumber(tranches, { maximumFractionDigits: 0 })} tramos · precio medio` : null;
}

function OperationCard({ tx }: { tx: InsiderFeedTransaction }) {
    const note = trancheNote(tx.tranches);
    return (
        <article className="min-w-0 rounded-lg border border-gray-800 bg-gray-900/50 p-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Link className="inline-flex min-h-11 min-w-11 items-center font-semibold text-teal-300 hover:text-teal-200" href={`/insider?ticker=${tx.ticker}`}>
                    {tx.ticker}
                </Link>
                <span className={`font-medium ${tx.side === 'compra' ? 'text-teal-300' : 'text-red-400'}`}>{sideLabel(tx.side)}</span>
                {tx.rule_10b5_1 ? <span className="text-xs text-gray-500">Plan 10b5-1</span> : null}
                {tx.form === 'PDMR' ? <span className="text-xs text-gray-500">PDMR (Reino Unido)</span> : null}
                {tx.form === 'CA-INSIDER' ? <span className="text-xs text-gray-500">Canadá · fuente no oficial (Yahoo)</span> : null}
                <span className="ml-auto tabular-nums text-xs text-gray-500">{tx.date ? formatDate(tx.date) : '—'}</span>
            </div>
            <div className="mt-1.5 text-sm font-medium text-gray-100">{insiderName(tx.insider)}</div>
            <div className="text-xs text-gray-500">{insiderRole(tx.role, tx.officer_title)}</div>
            <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
                <div>
                    <dt className="text-xs text-gray-500">Acciones</dt>
                    <dd className="tabular-nums text-gray-200">{formatNumber(tx.shares ?? null, { maximumFractionDigits: 0 })}</dd>
                </div>
                <div>
                    <dt className="text-xs text-gray-500">Precio</dt>
                    <dd className="tabular-nums text-gray-200">{usd(tx.price, 2, txCurrency(tx))}</dd>
                </div>
                <div>
                    <dt className="text-xs text-gray-500">Importe</dt>
                    <dd className="tabular-nums font-semibold text-gray-100">
                        {tx.source_url ? (
                            <a
                                className="inline-flex min-h-11 min-w-11 items-center gap-1 hover:text-teal-300"
                                href={tx.source_url}
                                rel="noopener noreferrer"
                                target="_blank"
                            >
                                {usd(tx.value, 0, txCurrency(tx))}
                                <ExternalLink aria-hidden="true" className="h-3 w-3" />
                            </a>
                        ) : (
                            usd(tx.value, 0, txCurrency(tx))
                        )}
                    </dd>
                </div>
            </dl>
            {note ? <p className="mt-1.5 text-xs text-gray-500">{note}</p> : null}
            {tx.currency == null && (tx.price != null || tx.value != null) ? (
                <p className="mt-1.5 text-xs text-gray-500">Divisa no informada</p>
            ) : null}
            {tx.form === 'PDMR' ? (
                <p className="mt-1.5 text-xs text-gray-500">Fuente: tracefour (CC BY 4.0) · documento original en FCA NSM</p>
            ) : null}
            {tx.form === 'CA-INSIDER' ? (
                <p className="mt-1.5 text-xs text-gray-500">
                    Fuente no oficial (Yahoo); la verdad oficial es{' '}
                    <a className="underline hover:text-teal-300" href="https://www.sedi.ca" rel="noopener noreferrer" target="_blank">SEDI</a>
                    {' '}(consulta manual)
                </p>
            ) : null}
        </article>
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
    const bigBuys = feed.big_buys ?? [];
    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Filter build={(value) => href(value, days)} current={side as 'all' | 'buy' | 'sell'} label="Lado" options={SIDES} />
                <Filter build={(value) => href(side, value)} current={days as 30 | 90 | 365} label="Periodo" options={PERIODS} />
            </div>

            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[
                    ['Compras', `${formatNumber(totals.buy_count, { maximumFractionDigits: 0 })} · ${typeof totals.buy_value === 'number' ? formatMarketCapUsd(totals.buy_value) : '—'}`],
                    ['Ventas', `${formatNumber(totals.sell_count, { maximumFractionDigits: 0 })} · ${typeof totals.sell_value === 'number' ? formatMarketCapUsd(totals.sell_value) : '—'}`],
                    ['Clusters', formatNumber(feed.clusters.length, { maximumFractionDigits: 0 })],
                    ['Compras CEO/CFO', formatNumber(feed.c_suite_buys.length, { maximumFractionDigits: 0 })],
                ].map(([label, value]) => (
                    <div className="rounded-xl border border-gray-800 bg-surface-1 p-4" key={label}>
                        <dt className="text-xs text-gray-500">{label}</dt>
                        <dd className="mt-1 text-xl font-bold tabular-nums text-gray-100">{value}</dd>
                    </div>
                ))}
            </dl>
            <p className="-mt-3 text-xs text-gray-500">
                Totales y señales: solo Form 4 (SEC, importes declarados en USD). Canadá (Yahoo, fuente no
                oficial) y PDMR del Reino Unido se listan en la tabla con su divisa declarada, sin sumarse aquí.
            </p>

            {feed.clusters.length > 0 ? (
                <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                    <h2 className="text-sm font-semibold text-gray-100">Clusters de compra</h2>
                    <ul className="mt-3 divide-y divide-gray-900 text-sm">
                        {feed.clusters.map((cluster) => (
                            <SignalLine key={`${cluster.ticker}-${cluster.window_start}`} signal={cluster}>
                                <span className="text-gray-300">{cluster.insider_count} insiders</span>
                            </SignalLine>
                        ))}
                    </ul>
                </section>
            ) : null}

            {bigBuys.length > 0 ? (
                <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                    <h2 className="text-sm font-semibold text-gray-100">Grandes compras</h2>
                    <p className="mt-1 text-xs text-gray-500">
                        Compras código P de más de 1 M$. Las marcadas «Institucional» son fondos o accionistas
                        de más del 10 % (p. ej. Berkshire), no insiders personales.
                    </p>
                    <ul className="mt-3 divide-y divide-gray-900 text-sm">
                        {bigBuys.map((buy) => (
                            <SignalLine key={`big-${buy.accession_number}-${buy.tx_line}`} signal={buy} />
                        ))}
                    </ul>
                </section>
            ) : null}

            {feed.c_suite_buys.length > 0 ? (
                <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                    <h2 className="text-sm font-semibold text-gray-100">Compras de CEO y CFO</h2>
                    <ul className="mt-3 divide-y divide-gray-900 text-sm">
                        {feed.c_suite_buys.map((buy) => (
                            <SignalLine key={`${buy.accession_number}-${buy.tx_line}`} signal={buy} />
                        ))}
                    </ul>
                </section>
            ) : null}

            <section className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                <h2 className="text-sm font-semibold text-gray-100">Operaciones</h2>
                {feed.transactions.length === 0 ? (
                    <p className="mt-3 text-sm text-gray-500">Sin operaciones en este periodo.</p>
                ) : (
                    <>
                        <div className="mt-3 hidden overflow-x-auto md:block">
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
                                    {feed.transactions.map((tx, index) => {
                                        const note = trancheNote(tx.tranches);
                                        return (
                                            <tr className="border-t border-gray-900" key={`${tx.accession_number}-${index}`}>
                                                <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-gray-400">{tx.date ? formatDate(tx.date) : '—'}</td>
                                                <td className="px-3 py-2 font-semibold">
                                                    <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300 hover:text-teal-200" href={`/insider?ticker=${tx.ticker}`}>
                                                        {tx.ticker}
                                                    </Link>
                                                    {tx.form === 'PDMR' ? <span className="block text-xs font-normal text-gray-500">PDMR (Reino Unido)</span> : null}
                                                    {tx.form === 'CA-INSIDER' ? <span className="block text-xs font-normal text-gray-500">Canadá · fuente no oficial (Yahoo)</span> : null}
                                                </td>
                                                <td className="px-3 py-2 text-gray-100">{insiderName(tx.insider)}</td>
                                                <td className="px-3 py-2 text-gray-400">{insiderRole(tx.role, tx.officer_title)}</td>
                                                <td className={`px-3 py-2 font-medium ${tx.side === 'compra' ? 'text-teal-300' : 'text-red-400'}`}>
                                                    {sideLabel(tx.side)}
                                                    {tx.rule_10b5_1 ? <span className="block text-xs font-normal text-gray-500">Plan 10b5-1</span> : null}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums">
                                                    {formatNumber(tx.shares ?? null, { maximumFractionDigits: 0 })}
                                                    {note ? <span className="block text-xs font-normal text-gray-500">{note}</span> : null}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums">{usd(tx.price, 2, txCurrency(tx))}</td>
                                                <td className="py-2 pl-3 text-right tabular-nums">
                                                    {tx.source_url ? (
                                                        <a
                                                            className="inline-flex min-h-11 min-w-11 items-center gap-1 text-gray-100 hover:text-teal-300"
                                                            href={tx.source_url}
                                                            rel="noopener noreferrer"
                                                            target="_blank"
                                                        >
                                                            {usd(tx.value, 0, txCurrency(tx))}
                                                            <ExternalLink aria-hidden="true" className="h-3 w-3" />
                                                        </a>
                                                    ) : (
                                                        usd(tx.value, 0, txCurrency(tx))
                                                    )}
                                                    {tx.currency == null && (tx.price != null || tx.value != null) ? (
                                                        <span className="block text-xs font-normal text-gray-500">Divisa no informada</span>
                                                    ) : null}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                        <div className="mt-3 grid grid-cols-1 gap-3 md:hidden">
                            {feed.transactions.map((tx, index) => (
                                <OperationCard key={`${tx.accession_number}-${index}`} tx={tx} />
                            ))}
                        </div>
                    </>
                )}
            </section>
        </div>
    );
}
