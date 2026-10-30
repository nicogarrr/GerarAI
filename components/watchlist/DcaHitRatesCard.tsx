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
 * Tabla «¿Cuántas veces estaba más arriba?» por nivel de compra: % de meses
 * confirmados con señal cuyo cierre era más alto N meses después. Solo
 * histórico: sin dato en una celda se dice, no se rellena.
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
            <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] border-separate border-spacing-y-1 text-xs">
                    <caption className="sr-only">Porcentaje de meses con señal cuyo cierre era más alto N meses después</caption>
                    <thead>
                        <tr className="text-gray-400">
                            <th scope="col" className="px-2 text-left font-medium">Señal</th>
                            {data.horizons.map((h) => (
                                <th key={h} scope="col" className="px-2 text-right font-medium">{h} m</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {data.rows.map((row) => (
                            <tr key={row.key}>
                                <th scope="row" className="px-2 py-1 text-left">
                                    <span
                                        className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                                        style={{ backgroundColor: row.color ?? '#374151', color: contrast(row.color) }}
                                    >
                                        {row.label}
                                    </span>
                                    <span className="ml-2 text-[11px] font-normal text-gray-500">{INT.format(row.signal_months)} meses con señal</span>
                                </th>
                                {row.cells.map((cell) => {
                                    const pct = dcaPercent(cell.pct_higher);
                                    const avg = dcaPercent(cell.avg_return);
                                    return (
                                        <td key={cell.horizon_months} className="px-2 py-1 text-right tabular-nums text-gray-200">
                                            {pct ?? <span className="text-gray-500">—</span>}
                                            {!compact && cell.months > 0 ? (
                                                <span className="block text-[10px] text-gray-500">
                                                    n={INT.format(cell.months)}{avg ? ` · media ${avg}` : ''}
                                                </span>
                                            ) : null}
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <p className="text-[11px] text-gray-500">
                {data.disclaimer} Solo meses confirmados; mide el precio, no la rentabilidad de una cartera.
            </p>
        </div>
    );
}
