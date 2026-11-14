'use client';

import Link from 'next/link';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { InsiderOperationsCompany, InsiderOperationsResult, InsiderOperationsSide } from '@/lib/actions/insider.actions';
import { insiderName, insiderRole } from '@/lib/insider/format';
import { PagedInsiderCompanies } from '@/components/insider/PagedInsiderCompanies';

/** Vista de operaciones insider (P/S) de cartera + watchlist, del agregado
 *  backend /api/insider/operations. Solo datos Form 4 persistidos: el
 *  periodo y lo no verificable se muestran siempre (Nico, 2026-10-19). */

const usdCompact = (f: Formatters, value: number) => f.formatMarketCapUsd(value);
const usdPrice = (f: Formatters, value: number | null) =>
    value === null ? '—' : f.formatPrice(value, 'USD', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const sharesText = (f: Formatters, side: InsiderOperationsSide) =>
    // Misma convención que el importe (86,74 M US$ · 300.000 acc. · 289,14 US$ en es-ES).
    side.trades === 0 ? '—' : f.formatNumber(side.shares, { maximumFractionDigits: 0 });
/** El total con filas sin importe es un mínimo: se marca en la cifra, no solo en el pie. */
const minMark = (side: InsiderOperationsSide) => (side.rows_without_value > 0 ? '≥ ' : '');

function SideCells({ side, empty, label }: { side: InsiderOperationsSide; empty?: string; label: string }) {
    const t = useT();
    const f = useFormat();
    if (side.trades === 0) {
        return (
            <TableCell className="block text-sm text-gray-500 md:table-cell md:text-right">
                <span className="block text-xs text-gray-500 md:hidden">{label}</span>
                {empty ?? '—'}
            </TableCell>
        );
    }
    return (
        <TableCell className="block text-sm md:table-cell md:text-right">
            <span className="block text-xs font-normal text-gray-500 md:hidden">{label}</span>
            <span className="font-semibold tabular-nums text-gray-100">{usdCompact(f, side.value)}</span>
            <span className="block text-xs font-normal text-gray-500">
                {t('insider.operations.sharesAcc', { n: sharesText(f, side) })} · {side.rows_without_value > 0 ? t('insider.operations.avgNaReason') : usdPrice(f, side.avg_price)}
            </span>
        </TableCell>
    );
}

function periodText(t: TFunction, f: Formatters, period: InsiderOperationsCompany['period']): string {
    if (!period.from || !period.to) return t('insider.operations.periodNoDates');
    return `${f.formatDate(period.from)} – ${f.formatDate(period.to)}`;
}

export function CompanyCard({ company }: { company: InsiderOperationsCompany }) {
    const t = useT();
    const f = useFormat();
    const { totals } = company;
    return (
        <Card className="min-w-0 rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Link
                    href={`/insider?ticker=${encodeURIComponent(company.ticker)}`}
                    className="font-mono text-base font-bold text-teal-300 hover:text-teal-200 hover:underline"
                >
                    {company.ticker}
                </Link>
                <span className="truncate text-sm text-gray-400">{company.company}</span>
                <Badge variant={company.origin === 'cartera' ? 'default' : 'outline'}>
                    {company.origin === 'cartera' ? t('insider.operations.originPortfolio') : t('insider.operations.originWatchlist')}
                </Badge>
                <span className="ml-auto text-xs text-gray-500">{periodText(t, f, company.period)}</span>
            </div>
            <p className="mt-1 text-xs text-gray-500">
                {t('insider.operations.totalsLine', {
                    sellMark: minMark(totals.sell),
                    sell: usdCompact(f, totals.sell.value),
                    buyMark: minMark(totals.buy),
                    buy: usdCompact(f, totals.buy.value),
                    filings: f.formatNumber(company.filings, { maximumFractionDigits: 0 }),
                    filingsUnit: company.filings === 1 ? t('insider.operations.filingOne') : t('insider.operations.filingMany'),
                })}
            </p>

            {/* Una sola tabla responsiva (decisión de diseño, 2026-11-14): fila
                tarjeta debajo de md, fila de tabla desde md; un insider = una fila
                con el mismo contenido en cada viewport. */}
            <div className="mt-3">
                <Table className="block md:table" regionLabel={t('insider.operations.tableRegion', { ticker: company.ticker })}>
                    <TableCaption className="sr-only">{t('insider.operations.tableCaption', { ticker: company.ticker })}</TableCaption>
                    <TableHeader className="hidden md:table-header-group">
                        <TableRow className="border-gray-700 hover:bg-transparent">
                            <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('insider.operations.colInsider')}</TableHead>
                            <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('insider.operations.colRole')}</TableHead>
                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('insider.operations.colSales')}</TableHead>
                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('insider.operations.colBuys')}</TableHead>
                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('insider.operations.colOps')}</TableHead>
                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('insider.operations.colLast')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody className="block space-y-2 md:table-row-group md:space-y-0">
                        {company.insiders.map((row) => (
                            <TableRow aria-label={insiderName(row.insider)} key={`${row.insider ?? 'sin-nombre'}|${row.role ?? ''}|${row.officer_title ?? ''}`} className="block rounded-lg border border-gray-700/50 bg-gray-900/50 p-3 md:table-row md:rounded-none md:border-0 md:border-b md:bg-transparent md:p-0">
                                <TableCell className="block text-sm text-gray-200 md:table-cell">
                                    <span className="block text-xs text-gray-500 md:hidden">{t('insider.operations.colInsider')}</span>
                                    <span className="font-medium md:font-normal">{insiderName(row.insider)}</span>
                                </TableCell>
                                <TableCell className="block text-sm text-gray-400 md:table-cell">
                                    <span className="block text-xs text-gray-500 md:hidden">{t('insider.operations.colRole')}</span>
                                    {insiderRole(row.role, row.officer_title, f.locale)}
                                </TableCell>
                                <SideCells side={row.sell} label={t('insider.operations.colSales')} />
                                <SideCells side={row.buy} label={t('insider.operations.colBuys')} />
                                <TableCell className="block text-sm tabular-nums text-gray-300 md:table-cell md:text-right">
                                    <span className="block text-xs text-gray-500 md:hidden">{t('insider.operations.colOps')}</span>
                                    {f.formatNumber(row.sell.trades + row.buy.trades, { maximumFractionDigits: 0 })}
                                </TableCell>
                                <TableCell className="block text-sm text-gray-400 md:table-cell md:text-right">
                                    <span className="block text-xs text-gray-500 md:hidden">{t('insider.operations.colLast')}</span>
                                    {row.last_tx ? f.formatDate(row.last_tx) : '—'}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            {company.excluded_codes > 0 ||
            company.excluded_derivative > 0 ||
            company.rows_without_date > 0 ||
            company.amended_filings > 0 ||
            company.totals.buy.rows_without_value + company.totals.sell.rows_without_value > 0 ? (
                <p className="mt-3 border-t border-gray-700/50 pt-2 text-xs text-gray-500">
                    {[
                        company.excluded_codes > 0
                            ? t('insider.operations.footExcludedCodes', {
                                count: f.formatCount(company.excluded_codes, t('insider.operations.excludedUnitOne'), t('insider.operations.excludedUnitMany')),
                                verb: company.excluded_codes === 1 ? t('insider.operations.footVerbOne') : t('insider.operations.footVerbMany'),
                            })
                            : null,
                        company.excluded_derivative > 0
                            ? t('insider.operations.footExcludedDerivatives', { n: f.formatNumber(company.excluded_derivative, { maximumFractionDigits: 0 }) })
                            : null,
                        company.totals.buy.rows_without_value + company.totals.sell.rows_without_value > 0
                            ? t('insider.operations.footRowsWithoutValue', { n: f.formatNumber(company.totals.buy.rows_without_value + company.totals.sell.rows_without_value, { maximumFractionDigits: 0 }) })
                            : null,
                        company.rows_without_date > 0
                            ? t('insider.operations.footRowsWithoutDate', { n: f.formatNumber(company.rows_without_date, { maximumFractionDigits: 0 }) })
                            : null,
                        company.amended_filings > 0
                            ? t('insider.operations.footAmended', { n: f.formatNumber(company.amended_filings, { maximumFractionDigits: 0 }) })
                            : null,
                    ].filter(Boolean).join(' ')}
                </p>
            ) : null}
        </Card>
    );
}

export default function InsiderOperationsView({ result, days }: { result: InsiderOperationsResult | null; days: number }) {
    const t = useT();
    const f = useFormat();
    if (!result || result.status !== 'ok') {
        return (
            <section aria-label={t('insider.operations.ariaLabel')} className="rounded-xl border border-gray-800 bg-surface-1 p-5 text-sm text-gray-400">
                {t('insider.operations.errorLoad')}
            </section>
        );
    }
    const daysText = f.formatNumber(days, { maximumFractionDigits: 0 });
    return (
        <section aria-label={t('insider.operations.ariaLabel')} className="flex flex-col gap-3">
            <div>
                <h2 className="text-sm font-semibold text-gray-100">{t('insider.operations.title')}</h2>
                <p className="mt-1 text-xs text-gray-500">{t('insider.operations.subtitle', { days: daysText })}</p>
                <details className="mt-1 text-xs text-gray-500">
                    <summary className="inline-flex min-h-11 cursor-pointer items-center">{t('insider.operations.coverageSummary')}</summary>
                    <p className="pb-2 leading-5">{t('insider.operations.coverageBody')}</p>
                </details>
            </div>
            {result.excluded_future_rows ? (
                <p role="status" className="text-xs text-amber-300">
                    {t('insider.operations.excludedFutureRows', { count: f.formatNumber(result.excluded_future_rows, { maximumFractionDigits: 0 }) })}
                </p>
            ) : null}
            {result.companies.length === 0 ? (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center text-sm text-gray-400">
                    {t('insider.operations.empty', { days: daysText })}
                </Card>
            ) : (
                <PagedInsiderCompanies companies={result.companies} />
            )}
            {result.companies_without_data.length > 0 ? (
                <p className="text-xs text-gray-500">
                    {t('insider.operations.withoutData', { tickers: result.companies_without_data.join(', ') })}
                </p>
            ) : null}
        </section>
    );
}
