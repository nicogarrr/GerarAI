import type { CSSProperties } from 'react';
import type { DcaHitRates } from '@/lib/dca/types';
import { dcaPercent } from '@/lib/dca/format';
import { intlLocale, type Locale } from '@/lib/i18n/locale';
import { t, type TranslationKey, type TranslationVars } from '@/lib/i18n/t';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
/** Fallback español sin RequestScope (tests y render directo): el acceso es de main (lib/i18n/t). */
const esT: TiFn = t;


function contrast(color: string | null): string {
    if (!color) return '#111827';
    const hex = color.replace('#', '');
    if (hex.length !== 6) return '#111827';
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
    return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#111827' : '#FFFFFF';
}

/**
 * Rejilla «¿Cuántas veces estaba más arriba?» por nivel de compra: % de meses
 * confirmados con señal cuyo cierre era más alto N meses después. Solo
 * histórico: sin dato en una celda se dice, no se rellena. Un solo DOM:
 * en móvil cada señal es una tarjeta con sus horizontes etiquetados (sin
 * scroll horizontal); desde sm se presenta como tabla de columnas.
 */

/** «Tiempo medio en 2X-4X»: solo visitas completadas reales; la abierta se declara aparte. */
function zoneVisitsLine(data: DcaHitRates, ti: TiFn, MONTHS: Intl.NumberFormat): string | null {
    const zv = data.zone_visits;
    if (!zv || !zv.available) return null;
    const open = zv.open_visit_months ? ti('watchlist.hitRates.zone.open', { months: MONTHS.format(zv.open_visit_months) }) : '';
    const ex = zv.excluded_gap_visits ?? 0;
    const excluded = ex > 0 ? (ex === 1 ? ti('watchlist.hitRates.zone.excludedOne', { count: ex }) : ti('watchlist.hitRates.zone.excludedOther', { count: ex })) : '';
    if (!zv.completed_visits || zv.avg_months === null) {
        return ti('watchlist.hitRates.zone.none', { open, excluded });
    }
    const n = zv.completed_visits;
    const vars = { months: MONTHS.format(zv.avg_months), count: n, open, excluded };
    return n === 1 ? ti('watchlist.hitRates.zone.avgOne', vars) : ti('watchlist.hitRates.zone.avgOther', vars);
}

export default function DcaHitRatesCard({ data, compact = false, scope = 'full', ti = esT, locale = 'es' }: {
    data: DcaHitRates | null;
    compact?: boolean;
    /** «range»: solo los meses con señal del rango elegido (p. ej. el backtest), no todo el histórico. */
    scope?: 'full' | 'range';
    /** Traductor y locale del idioma elegido (por defecto español). */
    ti?: TiFn;
    locale?: Locale;
}) {
    const INT = new Intl.NumberFormat(intlLocale(locale));
    const MONTHS = new Intl.NumberFormat(intlLocale(locale), { maximumFractionDigits: 1 });
    if (!data) {
        return <p className="text-xs text-gray-500">{ti('watchlist.hitRates.unavailable')}</p>;
    }
    if (!data.available) {
        return <p className="text-xs text-gray-500">{data.reason ?? ti('watchlist.hitRates.noHistory')}</p>;
    }
    return (
        <div className="space-y-2" data-testid="dca-hit-rates">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-gray-100">{ti('watchlist.hitRates.title')}</p>
                <p className="text-[11px] text-gray-500">
                    {ti('watchlist.hitRates.monthsCompleted', { count: INT.format(data.months_completed) })} · {scope === 'range' ? ti('watchlist.hitRates.scopeRange') : ti('watchlist.hitRates.scopeFull')}
                    {data.first_period ? ` (${data.first_period} – ${data.last_period})` : ''}
                </p>
            </div>
            {zoneVisitsLine(data, ti, MONTHS) ? (
                <p className="text-[11px] text-gray-400" data-testid="dca-zone-visits">{zoneVisitsLine(data, ti, MONTHS)}</p>
            ) : null}
            <div
                role="table"
                aria-label={ti('watchlist.hitRates.tableLabel')}
                className="space-y-2 sm:space-y-1"
                style={{ '--hcols': String(data.horizons.length) } as CSSProperties}
            >
                <div role="row" className="hidden border-b border-gray-800 pb-1 text-gray-400 sm:grid sm:grid-cols-[minmax(0,1.2fr)_repeat(var(--hcols),minmax(0,1fr))] sm:gap-x-2">
                    <span role="columnheader" className="px-1 text-left text-[11px] font-medium">{ti('watchlist.hitRates.signal')}</span>
                    {data.horizons.map((h) => (
                        <span key={h} role="columnheader" className="px-1 text-right text-[11px] font-medium">{ti('watchlist.hitRates.months', { count: h })}</span>
                    ))}
                </div>
                {data.rows.map((row) => (
                    <div
                        key={row.key}
                        role="row"
                        className="rounded-lg border border-gray-800/80 p-2 sm:grid sm:grid-cols-[minmax(0,1.2fr)_repeat(var(--hcols),minmax(0,1fr))] sm:gap-x-2 sm:rounded-none sm:border-0 sm:border-b sm:border-gray-800/60 sm:p-0 sm:py-1"
                    >
                        <div role="rowheader" className="mb-1.5 flex items-center gap-2 sm:mb-0 sm:px-1">
                            <span
                                className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                                style={{ backgroundColor: row.color ?? '#374151', color: contrast(row.color) }}
                            >
                                {row.label}
                            </span>
                            <span className="text-[11px] text-gray-500">{ti('watchlist.hitRates.signalMonths', { count: INT.format(row.signal_months) })}</span>
                        </div>
                        <div className="grid grid-cols-2 gap-1.5 sm:contents">
                            {row.cells.map((cell) => {
                                const pct = dcaPercent(cell.pct_higher, locale);
                                const avg = dcaPercent(cell.avg_return, locale);
                                return (
                                    <div key={cell.horizon_months} role="cell" className="rounded bg-gray-900/60 px-2 py-1 tabular-nums text-gray-200 sm:bg-transparent sm:px-1 sm:py-0 sm:text-right">
                                        <span className="block text-[10px] font-medium text-gray-500 sm:hidden">{ti('watchlist.hitRates.months', { count: cell.horizon_months })}</span>
                                        {pct ?? <span className="text-gray-500">—</span>}
                                        {!compact && cell.months > 0 ? (
                                            <span className="block text-[10px] text-gray-500">
                                                n={INT.format(cell.months)}{avg ? ` · ${ti('watchlist.hitRates.average', { avg })}` : ''}
                                            </span>
                                        ) : null}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>
            <p className="text-[11px] text-gray-500">
                {data.disclaimer} {ti('watchlist.hitRates.footer')}
            </p>
        </div>
    );
}
