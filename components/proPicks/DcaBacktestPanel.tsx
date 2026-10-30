'use client';

import { useState, useTransition } from 'react';
import { Loader2, Play, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaBacktest } from '@/lib/actions/dca-signals.actions';
import { formatMarketDate, parseLocalizedNumberDetailed } from '@/lib/format';
import type { DcaBacktest, DcaBacktestPlan } from '@/lib/dca/types';

/** «valorado al cierre de oct 2026» solo si el mes ha cerrado; si no, el último cierre con su fecha. */
export function valuationLabel(result: Pick<DcaBacktest, 'valued_at_period' | 'valued_at_date' | 'valued_month_complete'>): string {
    if (result.valued_month_complete === false && result.valued_at_date) {
        return `valorado al último cierre disponible (${formatMarketDate(result.valued_at_date)}, mes en curso)`;
    }
    return `valorado al cierre de ${result.valued_at_period ?? 'N/D'}`;
}

const NUM = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const pct = (v: number | null | undefined, sign = false) =>
    v === null || v === undefined
        ? '—'
        : new Intl.NumberFormat('es-ES', {
              style: 'percent',
              maximumFractionDigits: 1,
              minimumFractionDigits: 1,
              signDisplay: sign ? 'always' : 'auto',
          }).format(v);
const pp = (v: number | null | undefined) =>
    v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${NUM.format(v * 100)} pp`;

function money(v: number | null | undefined, unit: string): string {
    return v === null || v === undefined ? '—' : `${NUM.format(v)} ${unit}`;
}

function Row({ label, plans, render }: { label: string; plans: DcaBacktestPlan[]; render: (p: DcaBacktestPlan) => string }) {
    return (
        <tr className="border-t border-gray-700/60">
            <th scope="row" className="py-1.5 pr-3 text-left font-normal text-gray-400">
                {label}
            </th>
            {plans.map((p) => (
                <td key={p.key} className="py-1.5 pr-3 text-right tabular-nums text-gray-100">
                    {render(p)}
                </td>
            ))}
        </tr>
    );
}

/**
 * Backtest por ticker: DCA plano frente a DCA por niveles (Fórmula Nico v1) y
 * frente a niveles con presupuesto fijo. Mismo motor que las señales diarias,
 * sin look-ahead (veredicto con el cierre del mes y compra al primer cierre del
 * mes siguiente). Histórico e hipotético: no es asesoramiento.
 */
export default function DcaBacktestPanel({ defaultSymbol = 'UBER' }: { defaultSymbol?: string }) {
    const [symbol, setSymbol] = useState(defaultSymbol);
    const [start, setStart] = useState('2016-01');
    const [end, setEnd] = useState('');
    const [base, setBase] = useState('100');
    const [result, setResult] = useState<DcaBacktest | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [baseError, setBaseError] = useState<string | null>(null);
    const [pending, startTransition] = useTransition();

    const run = (event: React.FormEvent) => {
        event.preventDefault();
        // La aportación es dinero: nunca se reinterpreta en silencio
        // (Number(base) || 100 convertía «abc», «0» o «-50» en 100 sin avisar).
        const parsed = parseLocalizedNumberDetailed(base);
        if (!parsed.ok) {
            setBaseError(
                parsed.error === 'ambiguous'
                    ? 'Formato de número ambiguo: usa la coma para los decimales y el punto para los miles (ej. 1.234,56).'
                    : 'Introduce una aportación base mayor que 0.',
            );
            return;
        }
        if (parsed.value <= 0) {
            setBaseError('Introduce una aportación base mayor que 0.');
            return;
        }
        setBaseError(null);
        const baseAmount = parsed.value;
        startTransition(async () => {
            const { data, error: err } = await getDcaBacktest({
                symbol,
                start: start || undefined,
                end: end || undefined,
                base: baseAmount,
            });
            setResult(data);
            setError(err);
        });
    };

    const unit = result?.currency_label ?? result?.currency ?? '';
    const plans = result?.plans ?? [];
    const levels = plans.find((p) => p.key === 'levels');
    const fixed = plans.find((p) => p.key === 'fixed_budget');

    return (
        <Card className="w-full min-w-0 overflow-hidden rounded-lg border border-gray-700 bg-gray-800/50 p-4 sm:p-6" data-testid="dca-backtest">
            <div className="mb-4">
                <div className="mb-2 flex items-center gap-3">
                    <TrendingUp aria-hidden="true" className="h-6 w-6 text-teal-400" />
                    <h3 className="text-xl font-bold text-gray-100">Backtest DCA: plano vs por niveles</h3>
                </div>
                <p role="note" className="mb-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                    Experimental: este backtest simula datos históricos. No predice resultados futuros ni incluye necesariamente todos los costes, impuestos o restricciones de ejecución. No es una recomendación de inversión.
                </p>
                <p className="text-sm text-gray-400">
                    Fórmula Nico v1 (1X–4X según la distancia bajo la media de 30 meses ajustada por volatilidad).
                    Cada mes se decide con el cierre de ese mes y se compra al primer cierre del siguiente: sin mirar el futuro.
                </p>
            </div>
            <form onSubmit={run} className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
                <label className="text-xs text-gray-400">
                    Ticker
                    <input
                        value={symbol}
                        onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                        className="mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100"
                        required
                        maxLength={24}
                    />
                </label>
                <label className="text-xs text-gray-400">
                    Desde (mes)
                    <input type="month" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100" />
                </label>
                <label className="text-xs text-gray-400">
                    Hasta (mes)
                    <input type="month" value={end} onChange={(e) => setEnd(e.target.value)} className="mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100" />
                </label>
                <label className="text-xs text-gray-400">
                    Aportación base
                    <input type="text" inputMode="decimal" value={base} onChange={(e) => setBase(e.target.value)} aria-invalid={baseError !== null} aria-describedby={baseError ? 'dca-base-error' : undefined} className="mt-1 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-100" />
                    {baseError && (
                        <span id="dca-base-error" role="alert" className="mt-1 block text-xs text-red-400">
                            {baseError}
                        </span>
                    )}
                </label>
                <div className="flex items-end">
                    <Button type="submit" disabled={pending || !symbol.trim()} className="w-full min-h-[38px] bg-teal-600 hover:bg-teal-500">
                        {pending ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" /> : <Play aria-hidden="true" className="mr-2 h-4 w-4" />}
                        {pending ? 'Calculando…' : 'Ejecutar'}
                    </Button>
                </div>
            </form>

            {error && <p className="text-sm text-red-400" role="alert">No se pudo calcular el backtest: {error}</p>}
            {result && !result.available && <p className="text-sm text-gray-400">{result.reason ?? 'Sin datos suficientes para ese rango.'}</p>}

            {result?.available && (
                <div className="space-y-5">
                    <p className="text-xs text-gray-500">
                        {result.symbol} · señales {result.first_signal} – {result.last_signal} ({result.months} meses) · {valuationLabel(result)}
                        {unit ? ` · precios en ${unit}` : ''} · fórmula {result.params_version}
                    </p>
                    <div className="overflow-x-auto">
                        <table className="w-full min-w-[520px] text-sm">
                            <caption className="sr-only">Comparativa de planes DCA</caption>
                            <thead>
                                <tr className="text-xs text-gray-400">
                                    <th scope="col" className="pb-2 text-left font-medium">Métrica</th>
                                    {plans.map((p) => (
                                        <th key={p.key} scope="col" className="pb-2 pr-3 text-right font-medium">
                                            {p.label}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                <Row label="Dinero aportado" plans={plans} render={(p) => money(p.invested, unit)} />
                                <Row label="Valor final" plans={plans} render={(p) => money(p.final_value, unit)} />
                                <Row label="TIR anual" plans={plans} render={(p) => pct(p.irr)} />
                                <Row label="Coste medio por acción" plans={plans} render={(p) => money(p.avg_cost, unit)} />
                                <Row label="Máx. caída (TWR)" plans={plans} render={(p) => pct(p.max_drawdown)} />
                                <Row label="Peor pérdida latente" plans={plans} render={(p) => pct(p.worst_unrealized)} />
                                <Row label="Caja sin invertir al final" plans={plans} render={(p) => (p.cash_left ? money(p.cash_left, unit) : '—')} />
                            </tbody>
                        </table>
                    </div>
                    <ul className="space-y-1 text-xs text-gray-400">
                        {levels && (
                            <li>
                                Niveles aportando extra: TIR {pp(levels.irr_vs_plain)} vs plano; con el mismo dinero total compra{' '}
                                {pct(levels.shares_per_money_vs_plain, true)} acciones.
                            </li>
                        )}
                        {fixed && (
                            <li>
                                Presupuesto fijo (mismo dinero que el plano; en 1X invierte la mitad y guarda caja): valor final{' '}
                                {pct(fixed.value_vs_plain, true)} vs plano. En el histórico amplio esta variante suele quedar POR DEBAJO del DCA plano.
                            </li>
                        )}
                    </ul>
                    {result.levels.length > 0 && (
                        <div className="flex flex-wrap gap-2 text-xs">
                            {result.levels.map((l) => (
                                <span key={l.level} className="rounded border border-gray-700 px-2 py-1 text-gray-300">
                                    <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: l.color }} />
                                    {l.label}: {l.months} meses
                                </span>
                            ))}
                        </div>
                    )}
                    <DcaHitRatesCard data={result.hit_rates} scope="range" />
                    <p className="text-[11px] text-gray-500">{result.disclaimer}</p>
                </div>
            )}
        </Card>
    );
}
