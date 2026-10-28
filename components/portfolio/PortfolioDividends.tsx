import Link from 'next/link';
import type { PortfolioDividendProjection } from '@/lib/actions/portfolio.actions';
import { formatMoney, formatDate, formatPrice, formatCountEs } from '@/lib/format';
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

const monthLabel = (key: string): string => {
    // "2027-01" -> "ene 2027". Se parsea el dia 2 para no caer en el mes
    // anterior por zona horaria.
    const parsed = new Date(`${key}-02T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return key;
    return new Intl.DateTimeFormat('es-ES', { month: 'short', year: 'numeric' }).format(parsed);
};

type DividendPosition = PortfolioDividendProjection['positions'][number];

/** Tasa de retención en origen con su país y las condiciones/motivo pegados a la cifra
 *  (misma pieza en la tabla de escritorio y en la tarjeta móvil). */
function WithholdingNote({ position }: { position: DividendPosition }) {
    return (
        <>
            {position.source_withholding_rate === null
                ? 'N/D'
                : `${(position.source_withholding_rate * 100).toLocaleString('es-ES', { maximumFractionDigits: 1 })}%`}
            {position.domicile_country ? (
                <span className="ml-1 text-xs text-gray-500">({position.domicile_country})</span>
            ) : null}
            {position.source_withholding_rate !== null && position.withholding_kind === 'techo_convenio' ? (
                <span className="block text-xs text-gray-500">techo de convenio (escenario); la retención efectiva puede ser mayor</span>
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

function FiscalYearCard({ year, data, baseCurrency }: { year: string; data: PortfolioDividendProjection['fiscal_by_year'][string]; baseCurrency: string }) {
    const money = (value: number | null) => formatMoney(value, baseCurrency);
    const rows = fiscalCardRows(data);
    const note = fiscalYearNote(data);
    return (
        <div className="rounded-lg border border-gray-800 p-4">
            <p className="text-xs uppercase tracking-wide text-gray-500">Escenario {year}</p>
            <dl className="mt-3 space-y-1.5">
                {rows.map((row) => (
                    <div className="flex items-baseline justify-between gap-3" key={row.label}>
                        <dt className="text-xs text-gray-500">{row.label}</dt>
                        <dd className="text-sm font-medium text-gray-100">{money(row.value)}</dd>
                    </div>
                ))}
                {typeof data.effective_avg_rate === 'number' ? (
                    <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-xs text-gray-500">Tipo medio efectivo</dt>
                        <dd className="text-sm font-medium text-gray-100">
                            {`${(data.effective_avg_rate * 100).toLocaleString('es-ES', { maximumFractionDigits: 1 })}%`}
                        </dd>
                    </div>
                ) : null}
            </dl>
            {data.excluded_tickers.length > 0 ? (
                <p className="mt-3 text-xs text-amber-400/90">
                    Subconjunto cubierto: excluye <TickerList tickers={data.excluded_tickers} /> (sin datos, no cero).
                </p>
            ) : null}
            {note !== null ? (
                <p className="mt-2 text-xs leading-5 text-gray-500">{note}</p>
            ) : null}
        </div>
    );
}

function DeclaredFuturePanel({ items }: { items: PortfolioDividendProjection['declared_future'] }) {
    // La nota del backend ("según el proveedor de datos, no verificado contra
    // fuente primaria; no alimenta la réplica") es una salvedad de veracidad:
    // INGESTADO desde el proveedor no equivale a confirmación corporativa, y
    // la nota siempre llega a la pantalla (declaredFutureNoteView).
    const view = declaredFutureNoteView(items);
    const description = [
        view.sharedNote,
        view.sharedAsOf !== null ? `Datos al ${formatDate(view.sharedAsOf)}.` : null,
    ]
        .filter((part): part is string => part !== null)
        .join(' ') || undefined;
    return (
        <Panel title="Declarados con fecha futura" description={description}>
            <ul className="space-y-1.5 text-sm text-gray-300">
                {items.map((item, index) => (
                    <li key={`${item.ticker}-${item.ex_date}`}>
                        <Link
                            href={`/research/${encodeURIComponent(item.ticker)}`}
                            className="font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
                        >
                            {item.ticker}
                        </Link>
                        {` · ex ${formatDate(item.ex_date)} · pago ${item.pay_date ? formatDate(item.pay_date) : 'N/D'} · `}
                        {formatPrice(item.amount_per_share, item.currency)} por acción
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
export default function PortfolioDividends({ projection, userId }: { projection: PortfolioDividendProjection; userId?: string }) {
    const baseCurrency = projection.base_currency;
    const activeMonths = projection.months.filter(
        (month) => month.covered_tickers.length > 0 || month.excluded_tickers.length > 0,
    );
    const fiscalYears = Object.entries(projection.fiscal_by_year);
    const coverageLists: Array<{ label: string; tickers: string[] }> = [
        { label: 'Sin dividendos declarados registrados', tickers: projection.coverage.sin_datos },
        { label: 'Importe de dividendo incierto (excluidos del total)', tickers: projection.coverage.uncertain_dividends ?? [] },
        { label: 'Sin tipo de cambio', tickers: projection.coverage.fx_missing },
        { label: 'Retención de origen sin verificar', tickers: projection.coverage.unknown_source_withholding },
    ].filter((entry) => entry.tickers.length > 0);

    return (
        <div className="space-y-6">
            {userId ? <div className="flex justify-end"><SyncDividendsButton userId={userId} /></div> : null}
            {/* Sin badge INFERIDO/INGESTADO en cada tarjeta: la procedencia se explica
                en «Supuestos fiscales y fuentes» y en el aviso junto al bruto. */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                <span>
                    Proyección a {formatCountEs(projection.horizon_months, 'mes', 'meses')} · datos al {formatDate(projection.as_of)}
                </span>
            </div>

            {projection.gross_summary && projection.gross_summary.gross_total_base > 0 ? (
                <p className="text-sm text-gray-200">
                    {projection.gross_summary.complete === false ? 'Bruto parcial proyectado' : 'Bruto proyectado'} a {projection.horizon_months} meses:{' '}
                    <span className="font-semibold">{formatMoney(projection.gross_summary.gross_total_base, baseCurrency)}</span>
                    {projection.gross_summary.gross_unverified_base > 0 ? (
                        <span className="text-gray-400">
                            {' '}(de ellos {formatMoney(projection.gross_summary.gross_unverified_base, baseCurrency)} con retención en origen no verificada)
                        </span>
                    ) : null}
                    . INFERIDO: réplica de los dividendos de los últimos 12 meses, no pagos confirmados. Neto e IRPF: N/D salvo posiciones con retención verificada; donde hay cifra es un escenario (residencia fiscal ES, W-8BEN vigente para EE. UU., única renta del ahorro) y no el neto final.
                    {projection.coverage.fx_missing.length > 0 ? (
                        <span className="text-amber-400/90">
                            {' '}No incluye: {projection.coverage.fx_missing.length} {projection.coverage.fx_missing.length === 1 ? 'posición' : 'posiciones'} sin tipo de cambio ({projection.coverage.fx_missing.join(', ')}).
                        </span>
                    ) : null}
                    {projection.coverage.sin_datos.length > 0 ? (
                        <span className="text-gray-400">
                            {' '}Sin dividendos registrados: {projection.coverage.sin_datos.join(', ')}.
                        </span>
                    ) : null}
                </p>
            ) : null}

            {projection.positions.length === 0 && projection.declared_future.length === 0 ? (
                <Panel title="Proyección de dividendos">
                    <p className="text-sm text-gray-400">
                        {(projection.coverage.uncertain_dividends ?? []).length > 0
                            ? 'Sin proyección: importe de dividendo incierto.'
                            : 'Sin datos: ninguna posición de la cartera tiene dividendos declarados registrados.'}
                    </p>
                </Panel>
            ) : (
                <>
                    {fiscalYears.length > 0 ? (
                        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                            {fiscalYears.map(([year, data]) => (
                                <FiscalYearCard baseCurrency={baseCurrency} data={data} key={year} year={year} />
                            ))}
                        </div>
                    ) : null}

                    <Panel
                        title="Mes a mes"
                        description={`Bruto y retención de origen en ${baseCurrency}, solo posiciones con cobertura fiscal completa.`}
                    >
                        {activeMonths.length === 0 ? (
                            <p className="text-sm text-gray-400">
                                Ningún pago proyectado en {projection.horizon_months === 1 ? 'el próximo mes' : `los próximos ${formatCountEs(projection.horizon_months, 'mes', 'meses')}`} con los datos registrados.
                            </p>
                        ) : (
                            <div className="overflow-x-auto" role="region" aria-label="Proyección mes a mes" tabIndex={0}>
                                <table className="w-full text-left text-sm">
                                    <thead>
                                        <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
                                            <th className="py-2 pr-4">Mes</th>
                                            <th className="py-2 pr-4">Bruto</th>
                                            <th className="py-2 pr-4">Retención origen</th>
                                            <th className="py-2">Posiciones</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {activeMonths.map((month) => (
                                            <tr className="border-b border-gray-900 text-gray-300" key={month.month}>
                                                <td className="py-2 pr-4 font-medium text-gray-100">{monthLabel(month.month)}</td>
                                                <td className="py-2 pr-4">
                                                    {month.covered_tickers.length > 0
                                                        ? (
                                                            <span>
                                                                {formatMoney(month.gross_base, baseCurrency)}
                                                                {month.gross_unverified_base != null && month.gross_unverified_base > 0 ? (
                                                                    <span className="block text-[10px] text-amber-400/90">
                                                                        + {formatMoney(month.gross_unverified_base, baseCurrency)} bruto, retención sin verificar
                                                                    </span>
                                                                ) : null}
                                                            </span>
                                                        )
                                                        : month.gross_unverified_base != null && month.gross_unverified_base > 0
                                                            ? (
                                                                <span title="Importe bruto; retención en origen no verificada">
                                                                    {formatMoney(month.gross_unverified_base, baseCurrency)}
                                                                    <span className="block text-[10px] text-amber-400/90">bruto, retención sin verificar</span>
                                                                </span>
                                                            )
                                                            : 'N/D'}
                                                </td>
                                                <td className="py-2 pr-4">
                                                    {month.covered_tickers.length > 0
                                                        ? formatMoney(month.source_withheld_base, baseCurrency)
                                                        : 'N/D'}
                                                </td>
                                                <td className="py-2">
                                                    <TickerList tickers={month.covered_tickers} />
                                                    {month.excluded_tickers.length > 0 ? (
                                                        <span className="block text-xs text-amber-400/90">
                                                            Excluidas sin datos: <TickerList tickers={month.excluded_tickers} className="font-medium text-amber-300 underline-offset-2 hover:text-amber-200 hover:underline" />
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

                    <Panel title="Por posición">
                        <div className="hidden overflow-x-auto md:block" role="region" aria-label="Proyección por posición" tabIndex={0}>
                            <table className="w-full text-left text-sm">
                                <thead>
                                    <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
                                        <th className="py-2 pr-4">Posición</th>
                                        <th className="py-2 pr-4">Títulos</th>
                                        <th className="py-2 pr-4">Pagos 12 m</th>
                                        <th className="py-2 pr-4">Bruto ({baseCurrency})</th>
                                        <th className="py-2 pr-4">Retención origen</th>
                                        <th className="py-2">Retenido ({baseCurrency})</th>
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
                                                {formatPositionQuantity(position.quantity)}
                                            </td>
                                            <td className="py-2 pr-4">{position.frequency_last_year}</td>
                                            <td className="py-2 pr-4">{formatMoney(position.gross_base, baseCurrency)}</td>
                                            <td className="py-2 pr-4">
                                                <WithholdingNote position={position} />
                                            </td>
                                            <td className="py-2">{formatMoney(position.source_withheld_base, baseCurrency)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <ul className="space-y-3 md:hidden" aria-label="Proyección por posición (tarjetas)">
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
                                            {formatPositionQuantity(position.quantity)} títulos · pagos 12 m: {position.frequency_last_year}
                                        </span>
                                    </div>
                                    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
                                        <dt className="text-xs text-gray-500">Bruto ({baseCurrency})</dt>
                                        <dd className="text-right">{formatMoney(position.gross_base, baseCurrency)}</dd>
                                        <dt className="text-xs text-gray-500">Retenido ({baseCurrency})</dt>
                                        <dd className="text-right">{formatMoney(position.source_withheld_base, baseCurrency)}</dd>
                                    </dl>
                                    <div className="mt-2 border-t border-gray-900 pt-2">
                                        <span className="text-xs text-gray-500">Retención origen: </span>
                                        <WithholdingNote position={position} />
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </Panel>

                    {projection.declared_future.length > 0 ? (
                        <DeclaredFuturePanel items={projection.declared_future} />
                    ) : null}
                </>
            )}

            {coverageLists.length > 0 ? (
                <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3">
                    <p className="text-sm font-medium text-amber-200">Fuera de la proyección:</p>
                    <ul className="mt-1 space-y-1 text-sm text-amber-100/80">
                        {coverageLists.map((entry) => (
                            <li key={entry.label}>
                                {entry.label}: <TickerList tickers={entry.tickers} className="font-medium text-amber-300 underline-offset-2 hover:text-amber-200 hover:underline" />
                                {entry.label === 'Retención de origen sin verificar' && projection.coverage.unverified_reasons ? (
                                    <ul className="ml-4 mt-1 list-disc space-y-0.5 text-xs text-amber-100/70">
                                        {entry.tickers.map((ticker) => (
                                            <li key={ticker}>
                                                {ticker}: {projection.coverage.unverified_reasons?.[ticker] ?? 'retención no verificada'}
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
                <summary className="cursor-pointer select-none text-gray-400">Supuestos fiscales y fuentes</summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 leading-5">
                    {projection.fiscal_conditions.map((condition) => (
                        <li key={condition}>{condition}</li>
                    ))}
                </ul>
                {Object.keys(projection.sources).length > 0 ? (
                    <p className="mt-2">
                        Fuentes:{' '}
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
