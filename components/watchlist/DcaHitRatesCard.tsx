import type { CSSProperties } from 'react';
import type { DcaHitRates } from '@/lib/dca/types';
import { dcaPercent } from '@/lib/dca/format';

const INT = new Intl.NumberFormat('es-ES');

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
export default function DcaHitRatesCard({ data, compact = false, scope = 'full' }: {
    data: DcaHitRates | null;
    compact?: boolean;
    /** «range»: solo los meses con señal del rango elegido (p. ej. el backtest), no todo el histórico. */
    scope?: 'full' | 'range';
}) {
    if (!data) {
        return <p className="text-xs text-gray-500">Histórico de señales no disponible ahora mismo.</p>;
    }
    if (!data.available) {
        return <p className="text-xs text-gray-500">{data.reason ?? 'Aún sin histórico de señales para este ticker.'}</p>;
    }
    return (
        <div className="space-y-2" data-testid="dca-hit-rates">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-gray-100">¿Cuántas veces estaba más arriba?</p>
                <p className="text-[11px] text-gray-500">
                    {INT.format(data.months_completed)} meses completados · {scope === 'range' ? 'solo el rango elegido' : 'histórico completo'}
                    {data.first_period ? ` (${data.first_period} – ${data.last_period})` : ''}
                </p>
            </div>
            <div
                role="table"
                aria-label="Porcentaje de meses con señal cuyo cierre era más alto N meses después"
                className="space-y-2 sm:space-y-1"
                style={{ '--hcols': String(data.horizons.length) } as CSSProperties}
            >
                <div role="row" className="hidden border-b border-gray-800 pb-1 text-gray-400 sm:grid sm:grid-cols-[minmax(0,1.2fr)_repeat(var(--hcols),minmax(0,1fr))] sm:gap-x-2">
                    <span role="columnheader" className="px-1 text-left text-[11px] font-medium">Señal</span>
                    {data.horizons.map((h) => (
                        <span key={h} role="columnheader" className="px-1 text-right text-[11px] font-medium">{h} m</span>
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
                            <span className="text-[11px] text-gray-500">{INT.format(row.signal_months)} meses con señal</span>
                        </div>
                        <div className="grid grid-cols-2 gap-1.5 sm:contents">
                            {row.cells.map((cell) => {
                                const pct = dcaPercent(cell.pct_higher);
                                const avg = dcaPercent(cell.avg_return);
                                return (
                                    <div key={cell.horizon_months} role="cell" className="rounded bg-gray-900/60 px-2 py-1 tabular-nums text-gray-200 sm:bg-transparent sm:px-1 sm:py-0 sm:text-right">
                                        <span className="block text-[10px] font-medium text-gray-500 sm:hidden">{cell.horizon_months} m</span>
                                        {pct ?? <span className="text-gray-500">—</span>}
                                        {!compact && cell.months > 0 ? (
                                            <span className="block text-[10px] text-gray-500">
                                                n={INT.format(cell.months)}{avg ? ` · media ${avg}` : ''}
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
                {data.disclaimer} Solo meses confirmados; mide el precio, no la rentabilidad de una cartera.
            </p>
        </div>
    );
}
