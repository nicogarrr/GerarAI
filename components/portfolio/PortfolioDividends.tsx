import Link from 'next/link';
import type { PortfolioDividendProjection } from '@/lib/actions/portfolio.actions';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import { createFormatters, type Formatters } from '@/lib/format';
import { t, type TranslationKey } from '@/lib/i18n/t';
import { intlLocale } from '@/lib/i18n/locale';

const esT: TFunction = t;
const esF = createFormatters('es');
import SyncDividendsButton from '@/components/portfolio/SyncDividendsButton';
import { Panel } from '@/components/ui/panel';
import {
    declaredFutureNoteView,
    fiscalCardRows,
    fiscalYearNote,
    formatPositionQuantity,
} from '@/lib/portfolio-dividends-display';

/** Lista de tickers enlazados a su ficha: cada cifra de la proyección pertenece
 *  a una posición concreta, así que el ticker lleva a su pantalla. */
function TickerList({ tickers, className }: { tickers: string[]; className?: string }) {
    return (
        <>
            {tickers.map((ticker, index) => (
                <span key={ticker}>
                    {index > 0 ? ', ' : ''}
                    <Link
                        href={`/research/${encodeURIComponent(ticker)}`}
                        className={className ?? 'font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline'}
                    >
                        {ticker}
                    </Link>
                </span>
            ))}
        </>
    );
}

const monthLabel = (key: string, f: Formatters = esF): string => {
    // "2027-01" -> "ene 2027". Se parsea el dia 2 para no caer en el mes
    // anterior por zona horaria.
    const parsed = new Date(`${key}-02T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return key;
    return new Intl.DateTimeFormat(intlLocale(f.locale), { month: 'short', year: 'numeric' }).format(parsed);
};

type DividendPosition = PortfolioDividendProjection['positions'][number];

/** Tasa de retención en origen con su país y las condiciones/motivo pegados a la cifra
 *  (misma pieza en la tabla de escritorio y en la tarjeta móvil). */
function WithholdingNote({ position, ti = esT, f = esF }: { position: DividendPosition; ti?: TFunction; f?: Formatters }) {
    return (
        <>
            {position.source_withholding_rate === null
                ? ti('common.na')
                : `${f.formatNumber(position.source_withholding_rate * 100, { maximumFractionDigits: 1 })}%`}
            {position.domicile_country ? (
                <span className="ml-1 text-xs text-gray-500">({position.domicile_country})</span>
            ) : null}
            {position.source_withholding_rate !== null && position.withholding_kind === 'techo_convenio' ? (
                <span className="block text-xs text-gray-500">{ti('portfolio.dividends.withholdingCapNote')}</span>
            ) : null}
            {position.source_withholding_rate !== null && position.scenario_conditions ? (
                <span className="block max-w-xs text-xs text-amber-300/80 max-md:max-w-none">{position.scenario_conditions}</span>
            ) : null}
            {position.source_withholding_rate === null && position.unverified_reason ? (
                <span className="block max-w-xs text-xs text-amber-300/80 max-md:max-w-none">{position.unverified_reason}</span>
            ) : null}
        </>
    );
}

function FiscalYearCard({ year, data, baseCurrency, ti = esT, f = esF }: { year: string; data: PortfolioDividendProjection['fiscal_by_year'][string]; baseCurrency: string; ti?: TFunction; f?: Formatters }) {
    const money = (value: number | null) => f.formatMoney(value, baseCurrency);
    const rows = fiscalCardRows(data, f.locale === 'en' ? 'en' : 'es');
    const note = fiscalYearNote(data);
    return (
        <div className="rounded-lg border border-gray-800 p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">{ti('portfolio.dividends.fiscalScenario', { year })}</p>
            <dl className="mt-3 space-y-1.5">
                {rows.map((row) => (
                    <div className="flex items-baseline justify-between gap-3" key={row.label}>
                        <dt className="text-xs text-gray-500">{row.label}</dt>
                        <dd className="text-sm font-medium text-gray-100">{money(row.value)}</dd>
                    </div>
                ))}
                {typeof data.effective_avg_rate === 'number' ? (
                    <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-xs text-gray-500">{ti('portfolio.dividends.effRate')}</dt>
                        <dd className="text-sm font-medium text-gray-100">
                            {`${f.formatNumber(data.effective_avg_rate * 100, { maximumFractionDigits: 1 })}%`}
                        </dd>
                    </div>
                ) : null}
            </dl>
            {data.excluded_tickers.length > 0 ? (
                <p className="mt-3 text-xs text-amber-400/90">
                    {ti('portfolio.dividends.subsetPrefix')}<TickerList tickers={data.excluded_tickers} />{ti('portfolio.dividends.subsetSuffix')}
                </p>
            ) : null}
            {note !== null ? (
                <p className="mt-2 text-xs leading-5 text-gray-500">{note}</p>
            ) : null}
        </div>
    );
}

function DeclaredFuturePanel({ items, ti = esT, f = esF }: { items: PortfolioDividendProjection['declared_future']; ti?: TFunction; f?: Formatters }) {
    // La nota del backend ("según el proveedor de datos, no verificado contra
    // fuente primaria; no alimenta la réplica") es una salvedad de veracidad:
    // INGESTADO desde el proveedor no equivale a confirmación corporativa, y
    // la nota siempre llega a la pantalla (declaredFutureNoteView).
    const view = declaredFutureNoteView(items);
    const description = [
        view.sharedNote,
        view.sharedAsOf !== null ? ti('portfolio.dividends.declaredAsOf', { date: f.formatDate(view.sharedAsOf) }) : null,
    ]
        .filter((part): part is string => part !== null)
        .join(' ') || undefined;
    return (
        <Panel title={ti('portfolio.dividends.declaredTitle')} description={description}>
            <ul className="space-y-1.5 text-sm text-gray-300">
                {items.map((item, index) => (
                    <li key={`${item.ticker}-${item.ex_date}`}>
                        <Link
                            href={`/research/${encodeURIComponent(item.ticker)}`}
                            className="font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
                        >
                            {item.ticker}
                        </Link>
                        {ti('portfolio.dividends.declaredItemLine', { exDate: f.formatDate(item.ex_date), payDate: item.pay_date ? f.formatDate(item.pay_date) : ti('common.na') })}
                        {ti('portfolio.dividends.perShare', { price: f.formatPrice(item.amount_per_share, item.currency) })}
                        <span className="ml-2 rounded border border-gray-700 px-1.5 py-0.5 text-xs text-gray-400">
                            {item.label} · {item.source}
                        </span>
                        {view.perItemNotes[index] !== null ? (
                            <span className="block text-xs text-gray-500">{view.perItemNotes[index]}</span>
                        ) : null}
                    </li>
                ))}
            </ul>
        </Panel>
    );
}

/**
 * Proyección mecánica de dividendos (idea 5 del listado 0-31). Toda cifra
 * llega calculada del endpoint determinista /api/portfolio/dividends/projection:
 * la UI no suma, infiere ni estima nada por su cuenta. Lo que el backend
 * marca como null se pinta N/D (nunca 0,00); la etiqueta INFERIDO, las notas
 * de veracidad y las condiciones del escenario fiscal viajan con los datos.
 */
export default function PortfolioDividends({ projection, userId, ti = esT, f = esF }: { projection: PortfolioDividendProjection; userId?: string; ti?: TFunction; f?: Formatters }) {
    const baseCurrency = projection.base_currency;
    const monthsText = projection.horizon_months === 1
        ? ti('portfolio.dividends.monthCountOne')
        : ti('portfolio.dividends.monthCountMany', { n: projection.horizon_months });
    const nextWindow = projection.horizon_months === 1
        ? ti('portfolio.dividends.nextMonthOne')
        : ti('portfolio.dividends.nextMonthMany', { n: projection.horizon_months });
    const positionWord = projection.coverage.fx_missing.length === 1
        ? ti('portfolio.dividends.positionOne')
        : ti('portfolio.dividends.positionMany');
    const coverageLabels: Record<string, TranslationKey> = {
        sin_datos: 'portfolio.dividends.covNoData',
        uncertain_dividends: 'portfolio.dividends.covUncertain',
        fx_missing: 'portfolio.dividends.covNoFx',
        unknown_source_withholding: 'portfolio.dividends.covWithholding',
    };
    const activeMonths = projection.months.filter(
        (month) => month.covered_tickers.length > 0 || month.excluded_tickers.length > 0,
    );
    const fiscalYears = Object.entries(projection.fiscal_by_year);
    const coverageLists: Array<{ label: string; key: TranslationKey; tickers: string[] }> = [
        { key: coverageLabels.sin_datos, label: ti(coverageLabels.sin_datos), tickers: projection.coverage.sin_datos },
        { key: coverageLabels.uncertain_dividends, label: ti(coverageLabels.uncertain_dividends), tickers: projection.coverage.uncertain_dividends ?? [] },
        { key: coverageLabels.fx_missing, label: ti(coverageLabels.fx_missing), tickers: projection.coverage.fx_missing },
        { key: coverageLabels.unknown_source_withholding, label: ti(coverageLabels.unknown_source_withholding), tickers: projection.coverage.unknown_source_withholding },
    ].filter((entry) => entry.tickers.length > 0);

    return (
        <div className="space-y-6">
            {userId ? <div className="flex justify-end"><SyncDividendsButton userId={userId} /></div> : null}
            {/* Sin badge INFERIDO/INGESTADO en cada tarjeta: la procedencia se explica
                en «Supuestos fiscales y fuentes» y en el aviso junto al bruto. */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                <span>
                    {ti('portfolio.dividends.projectionLine', { months: monthsText, date: f.formatDate(projection.as_of) })}
                </span>
            </div>

            {projection.gross_summary && projection.gross_summary.gross_total_base > 0 ? (
                <p className="text-sm text-gray-200">
                    {projection.gross_summary.complete === false
                        ? ti('portfolio.dividends.grossPartial', { n: projection.horizon_months })
                        : ti('portfolio.dividends.grossComplete', { n: projection.horizon_months })}{' '}
                    <span className="font-semibold">{f.formatMoney(projection.gross_summary.gross_total_base, baseCurrency)}</span>
                    {projection.gross_summary.gross_unverified_base > 0 ? (
                        <span className="text-gray-400">
                            {' '}{ti('portfolio.dividends.grossUnverified', { amount: f.formatMoney(projection.gross_summary.gross_unverified_base, baseCurrency) })}
                        </span>
                    ) : null}
                    . {ti('portfolio.dividends.grossInferredNote')}
                    {projection.coverage.fx_missing.length > 0 ? (
                        <span className="text-amber-400/90">
                            {' '}{ti('portfolio.dividends.grossFxExcluded', { count: projection.coverage.fx_missing.length, positions: positionWord, tickers: projection.coverage.fx_missing.join(', ') })}
                        </span>
                    ) : null}
                    {projection.coverage.sin_datos.length > 0 ? (
                        <span className="text-gray-400">
                            {' '}{ti('portfolio.dividends.grossNoDividends', { tickers: projection.coverage.sin_datos.join(', ') })}
                        </span>
                    ) : null}
                </p>
            ) : null}

            {projection.positions.length === 0 && projection.declared_future.length === 0 ? (
                <Panel title={ti('portfolio.dividends.panelTitle')}>
                    <p className="text-sm text-gray-400">
                        {(projection.coverage.uncertain_dividends ?? []).length > 0
                            ? ti('portfolio.dividends.emptyUncertain')
                            : ti('portfolio.dividends.emptyNoData')}
                    </p>
                </Panel>
            ) : (
                <>
                    {fiscalYears.length > 0 ? (
                        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                            {fiscalYears.map(([year, data]) => (
                                <FiscalYearCard baseCurrency={baseCurrency} data={data} key={year} year={year} ti={ti} f={f} />
                            ))}
                        </div>
                    ) : null}

                    <Panel
                        title={ti('portfolio.dividends.monthPanelTitle')}
                        description={ti('portfolio.dividends.monthPanelDesc', { currency: baseCurrency })}
                    >
                        {activeMonths.length === 0 ? (
                            <p className="text-sm text-gray-400">
                                {ti('portfolio.dividends.noPayments', { window: nextWindow })}
                            </p>
                        ) : (
                            <div className="overflow-x-auto" role="region" aria-label={ti('portfolio.dividends.regionMonth')} tabIndex={0}>
                                <table className="w-full text-left text-sm">
                                    <thead>
                                        <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
                                            <th className="py-2 pr-4">{ti('portfolio.dividends.thMonth')}</th>
                                            <th className="py-2 pr-4">{ti('portfolio.dividends.thGross')}</th>
                                            <th className="py-2 pr-4">{ti('portfolio.dividends.thWithholding')}</th>
                                            <th className="py-2">{ti('portfolio.dividends.thPositions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {activeMonths.map((month) => (
                                            <tr className="border-b border-gray-900 text-gray-300" key={month.month}>
                                                <td className="py-2 pr-4 font-medium text-gray-100">{monthLabel(month.month, f)}</td>
                                                <td className="py-2 pr-4">
                                                    {month.covered_tickers.length > 0
                                                        ? (
                                                            <span>
                                                                {f.formatMoney(month.gross_base, baseCurrency)}
                                                                {month.gross_unverified_base != null && month.gross_unverified_base > 0 ? (
                                                                    <span className="block text-[10px] text-amber-400/90">
                                                                        {ti('portfolio.dividends.unverifiedGross', { amount: f.formatMoney(month.gross_unverified_base, baseCurrency) })}
                                                                    </span>
                                                                ) : null}
                                                            </span>
                                                        )
                                                        : month.gross_unverified_base != null && month.gross_unverified_base > 0
                                                            ? (
                                                                <span title={ti('portfolio.dividends.grossOnlyTitle')}>
                                                                    {f.formatMoney(month.gross_unverified_base, baseCurrency)}
                                                                    <span className="block text-[10px] text-amber-400/90">{ti('portfolio.dividends.grossOnly')}</span>
                                                                </span>
                                                            )
                                                            : ti('common.na')}
                                                </td>
                                                <td className="py-2 pr-4">
                                                    {month.covered_tickers.length > 0
                                                        ? f.formatMoney(month.source_withheld_base, baseCurrency)
                                                        : ti('common.na')}
                                                </td>
                                                <td className="py-2">
                                                    <TickerList tickers={month.covered_tickers} />
                                                    {month.excluded_tickers.length > 0 ? (
                                                        <span className="block text-xs text-amber-400/90">
                                                            {ti('portfolio.dividends.excludedNoData')}<TickerList tickers={month.excluded_tickers} className="font-medium text-amber-300 underline-offset-2 hover:text-amber-200 hover:underline" />
                                                        </span>
                                                    ) : null}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </Panel>

                    <Panel title={ti('portfolio.dividends.perPositionTitle')}>
                        <div className="hidden overflow-x-auto md:block" role="region" aria-label={ti('portfolio.dividends.regionPosition')} tabIndex={0}>
                            <table className="w-full text-left text-sm">
                                <thead>
                                    <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
                                        <th className="py-2 pr-4">{ti('portfolio.dividends.thPosition')}</th>
                                        <th className="py-2 pr-4">{ti('portfolio.dividends.thShares')}</th>
                                        <th className="py-2 pr-4">{ti('portfolio.dividends.thPayments')}</th>
                                        <th className="py-2 pr-4">{ti('portfolio.dividends.thGrossCur', { currency: baseCurrency })}</th>
                                        <th className="py-2 pr-4">{ti('portfolio.dividends.thWithholding')}</th>
                                        <th className="py-2">{ti('portfolio.dividends.thWithheldCur', { currency: baseCurrency })}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {projection.positions.map((position) => (
                                        <tr className="border-b border-gray-900 text-gray-300" key={position.ticker}>
                                            <td className="py-2 pr-4 font-medium">
                                                <Link
                                                    href={`/research/${encodeURIComponent(position.ticker)}`}
                                                    className="text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
                                                >
                                                    {position.ticker}
                                                </Link>
                                            </td>
                                            <td className="py-2 pr-4">
                                                {formatPositionQuantity(position.quantity, f.locale === 'en' ? 'en' : 'es')}
                                            </td>
                                            <td className="py-2 pr-4">{position.frequency_last_year}</td>
                                            <td className="py-2 pr-4">{f.formatMoney(position.gross_base, baseCurrency)}</td>
                                            <td className="py-2 pr-4">
                                                <WithholdingNote position={position} ti={ti} f={f} />
                                            </td>
                                            <td className="py-2">{f.formatMoney(position.source_withheld_base, baseCurrency)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <ul className="space-y-3 md:hidden" aria-label={ti('portfolio.dividends.regionPositionCards')}>
                            {projection.positions.map((position) => (
                                <li className="rounded-lg border border-gray-800 p-3 text-sm text-gray-300" key={position.ticker}>
                                    <div className="flex items-baseline justify-between gap-3">
                                        <Link
                                            href={`/research/${encodeURIComponent(position.ticker)}`}
                                            className="font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
                                        >
                                            {position.ticker}
                                        </Link>
                                        <span className="text-xs text-gray-500">
                                            {ti('portfolio.dividends.sharesLine', { quantity: formatPositionQuantity(position.quantity, f.locale === 'en' ? 'en' : 'es'), count: position.frequency_last_year })}
                                        </span>
                                    </div>
                                    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
                                        <dt className="text-xs text-gray-500">{ti('portfolio.dividends.thGrossCur', { currency: baseCurrency })}</dt>
                                        <dd className="text-right">{f.formatMoney(position.gross_base, baseCurrency)}</dd>
                                        <dt className="text-xs text-gray-500">{ti('portfolio.dividends.thWithheldCur', { currency: baseCurrency })}</dt>
                                        <dd className="text-right">{f.formatMoney(position.source_withheld_base, baseCurrency)}</dd>
                                    </dl>
                                    <div className="mt-2 border-t border-gray-900 pt-2">
                                        <span className="text-xs text-gray-500">{ti('portfolio.dividends.withholdingPrefix')}</span>
                                        <WithholdingNote position={position} ti={ti} f={f} />
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </Panel>

                    {projection.declared_future.length > 0 ? (
                        <DeclaredFuturePanel items={projection.declared_future} ti={ti} f={f} />
                    ) : null}
                </>
            )}

            {coverageLists.length > 0 ? (
                <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3">
                    <p className="text-sm font-medium text-amber-200">{ti('portfolio.dividends.outsideTitle')}</p>
                    <ul className="mt-1 space-y-1 text-sm text-amber-100/80">
                        {coverageLists.map((entry) => (
                            <li key={entry.label}>
                                {entry.label}: <TickerList tickers={entry.tickers} className="font-medium text-amber-300 underline-offset-2 hover:text-amber-200 hover:underline" />
                                {entry.key === coverageLabels.unknown_source_withholding && projection.coverage.unverified_reasons ? (
                                    <ul className="ml-4 mt-1 list-disc space-y-0.5 text-xs text-amber-100/70">
                                        {entry.tickers.map((ticker) => (
                                            <li key={ticker}>
                                                {ticker}: {projection.coverage.unverified_reasons?.[ticker] ?? ti('portfolio.dividends.reasonFallback')}
                                            </li>
                                        ))}
                                    </ul>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}

            <details className="rounded-lg border border-gray-800 p-3 text-xs text-gray-500">
                <summary className="cursor-pointer select-none text-gray-400">{ti('portfolio.dividends.assumptions')}</summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 leading-5">
                    {projection.fiscal_conditions.map((condition) => (
                        <li key={condition}>{condition}</li>
                    ))}
                </ul>
                {Object.keys(projection.sources).length > 0 ? (
                    <p className="mt-2">
                        {ti('portfolio.dividends.sourcesLabel')}{' '}
                        {Object.values(projection.sources).map((url) => (
                            <a
                                className="mr-3 break-all text-teal-400 underline decoration-teal-800 underline-offset-2 hover:text-teal-300"
                                href={url}
                                key={url}
                                rel="noopener noreferrer"
                                target="_blank"
                            >
                                {new URL(url).hostname.replace(/^www\d*\./, '')}
                            </a>
                        ))}
                    </p>
                ) : null}
            </details>
        </div>
    );
}
