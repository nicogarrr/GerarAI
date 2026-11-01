'use client';

import { useState, useTransition } from 'react';
import { useLocale, useT } from '@/lib/i18n/client';
import { Loader2, Play, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaBacktest } from '@/lib/actions/dca-signals.actions';
import { formatMarketDate, parseLocalizedNumberDetailed } from '@/lib/format';
import type { DcaBacktest, DcaBacktestPlan } from '@/lib/dca/types';
import type { Locale } from '@/lib/i18n/locale';

/** «valorado al cierre de oct 2026» solo si el mes ha cerrado; si no, el último cierre con su fecha. */
export function valuationLabel(
    result: Pick<DcaBacktest, 'valued_at_period' | 'valued_at_date' | 'valued_month_complete'>,
    locale: Locale = 'es',
): string {
    const en = locale === 'en';
    if (result.valued_month_complete === false && result.valued_at_date) {
        const date = formatMarketDate(result.valued_at_date, undefined, undefined, locale);
        return en
            ? `valued at the latest available close (${date}, month in progress)`
            : `valorado al último cierre disponible (${date}, mes en curso)`;
    }
    return en
        ? `valued at the close of ${result.valued_at_period ?? 'n/a'}`
        : `valorado al cierre de ${result.valued_at_period ?? 'N/D'}`;
}

/** Formatos numéricos del panel en el idioma elegido (es-ES por defecto). */
function panelFormats(locale: Locale) {
    const tag = locale === 'en' ? 'en-US' : 'es-ES';
    const num = new Intl.NumberFormat(tag, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
    const pct = (v: number | null | undefined, sign = false) =>
        v === null || v === undefined
            ? '—'
            : new Intl.NumberFormat(tag, {
                  style: 'percent',
                  maximumFractionDigits: 1,
                  minimumFractionDigits: 1,
                  signDisplay: sign ? 'always' : 'auto',
              }).format(v);
    const pp = (v: number | null | undefined) =>
        v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${num.format(v * 100)} pp`;
    const money = (v: number | null | undefined, unit: string): string =>
        v === null || v === undefined ? '—' : `${num.format(v)} ${unit}`;
    return { pct, pp, money };
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
    const [rangeError, setRangeError] = useState<string | null>(null);
    const [pending, startTransition] = useTransition();
    const t = useT();
    const locale = useLocale();
    const { pct, pp, money } = panelFormats(locale);

    const run = (event: React.FormEvent) => {
        event.preventDefault();
        // «YYYY-MM» ordena como texto: un inicio posterior al final no se envía
        // (el backend respondía 422 y la tabla anterior seguía en pantalla).
        if (start && end && start > end) {
            setRangeError(t('propicks.dcaBacktest.rangeError'));
            return;
        }
        setRangeError(null);
        // La aportación es dinero: nunca se reinterpreta en silencio
        // (Number(base) || 100 convertía «abc», «0» o «-50» en 100 sin avisar).
        const parsed = parseLocalizedNumberDetailed(base, locale);
        if (!parsed.ok) {
            setBaseError(
                parsed.error === 'ambiguous'
                    ? t('propicks.dcaBacktest.baseAmbiguous')
                    : t('propicks.dcaBacktest.basePositive'),
            );
            return;
        }
        if (parsed.value <= 0) {
            setBaseError(t('propicks.dcaBacktest.basePositive'));
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
                    <h3 className="text-xl font-bold text-gray-100">{t('propicks.dcaBacktest.title')}</h3>
                </div>
                <p role="note" className="mb-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                    {t('propicks.dcaBacktest.experimental')}
                </p>
                <p className="text-sm text-gray-400">
                    {t('propicks.dcaBacktest.formula')}
                </p>
            </div>
            <form onSubmit={run} className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
                <label className="text-xs text-gray-400">
                    Ticker
                    <input
                        value={symbol}
                        onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                        className="mt-1 min-h-11 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-base text-gray-100 sm:min-h-0 sm:text-sm"
                        required
                        maxLength={24}
                    />
                </label>
                <label className="text-xs text-gray-400">
                    {t('propicks.dcaBacktest.from')}
                    <input type="month" value={start} onChange={(e) => setStart(e.target.value)} className="mt-1 min-h-11 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-base text-gray-100 sm:min-h-0 sm:text-sm" />
                </label>
                <label className="text-xs text-gray-400">
                    {t('propicks.dcaBacktest.to')}
                    <input type="month" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} aria-invalid={rangeError !== null} aria-describedby={rangeError ? 'dca-range-error' : undefined} className="mt-1 min-h-11 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-base text-gray-100 sm:min-h-0 sm:text-sm" />
                    {rangeError && (
                        <span id="dca-range-error" role="alert" className="mt-1 block text-xs text-red-400">
                            {rangeError}
                        </span>
                    )}
                </label>
                <label className="text-xs text-gray-400">
                    {t('propicks.dcaBacktest.base')}
                    <input type="text" inputMode="decimal" value={base} onChange={(e) => setBase(e.target.value)} aria-invalid={baseError !== null} aria-describedby={baseError ? 'dca-base-error' : undefined} className="mt-1 min-h-11 w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-base text-gray-100 sm:min-h-0 sm:text-sm" />
                    {baseError && (
                        <span id="dca-base-error" role="alert" className="mt-1 block text-xs text-red-400">
                            {baseError}
                        </span>
                    )}
                </label>
                <div className="flex items-end">
                    <Button type="submit" disabled={pending || !symbol.trim()} className="w-full min-h-[38px] bg-teal-600 hover:bg-teal-500">
                        {pending ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" /> : <Play aria-hidden="true" className="mr-2 h-4 w-4" />}
                        {pending ? t('propicks.dcaBacktest.running') : t('propicks.dcaBacktest.run')}
                    </Button>
                </div>
            </form>

            {error && <p className="text-sm text-red-400" role="alert">{t('propicks.dcaBacktest.error', { error })}</p>}
            {result && !result.available && <p className="text-sm text-gray-400">{result.reason ?? t('propicks.dcaBacktest.notEnoughData')}</p>}

            {result?.available && (
                <div className="space-y-5">
                    <p className="text-xs text-gray-500">
                        {t('propicks.dcaBacktest.summary', { symbol: result.symbol, first: result.first_signal ?? '—', last: result.last_signal ?? '—', months: result.months })} · {valuationLabel(result, locale)}
                        {unit ? ` · ${t('propicks.dcaBacktest.pricesIn', { unit })}` : ''} · {t('propicks.dcaBacktest.formulaVersion', { version: result.params_version ?? '—' })}
                    </p>
                    <div className="overflow-x-auto">
                        <table className="w-full min-w-[520px] text-sm">
                            <caption className="sr-only">{t('propicks.dcaBacktest.caption')}</caption>
                            <thead>
                                <tr className="text-xs text-gray-400">
                                    <th scope="col" className="pb-2 text-left font-medium">{t('propicks.dcaBacktest.metric')}</th>
                                    {plans.map((p) => (
                                        <th key={p.key} scope="col" className="pb-2 pr-3 text-right font-medium">
                                            {p.label}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                <Row label={t('propicks.dcaBacktest.invested')} plans={plans} render={(p) => money(p.invested, unit)} />
                                <Row label={t('propicks.dcaBacktest.finalValue')} plans={plans} render={(p) => money(p.final_value, unit)} />
                                <Row label={t('propicks.dcaBacktest.irr')} plans={plans} render={(p) => pct(p.irr)} />
                                <Row label={t('propicks.dcaBacktest.avgCost')} plans={plans} render={(p) => money(p.avg_cost, unit)} />
                                <Row label={t('propicks.dcaBacktest.maxDrawdown')} plans={plans} render={(p) => pct(p.max_drawdown)} />
                                <Row label={t('propicks.dcaBacktest.worstUnrealized')} plans={plans} render={(p) => pct(p.worst_unrealized)} />
                                <Row label={t('propicks.dcaBacktest.cashLeft')} plans={plans} render={(p) => (p.cash_left ? money(p.cash_left, unit) : '—')} />
                            </tbody>
                        </table>
                    </div>
                    <ul className="space-y-1 text-xs text-gray-400">
                        {levels && (
                            <li>
                                {t('propicks.dcaBacktest.levelsNote', { irr: pp(levels.irr_vs_plain), shares: pct(levels.shares_per_money_vs_plain, true) })}
                            </li>
                        )}
                        {fixed && (
                            <li>
                                {t('propicks.dcaBacktest.fixedNote', { value: pct(fixed.value_vs_plain, true) })}
                            </li>
                        )}
                    </ul>
                    {result.levels.length > 0 && (
                        <div className="flex flex-wrap gap-2 text-xs">
                            {result.levels.map((l) => (
                                <span key={l.level} className="rounded border border-gray-700 px-2 py-1 text-gray-300">
                                    <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: l.color }} />
                                    {t('propicks.dcaBacktest.levelMonths', { label: l.label, months: l.months })}
                                </span>
                            ))}
                        </div>
                    )}
                    <DcaHitRatesCard data={result.hit_rates} scope="range" ti={t} locale={locale} />
                    <p className="text-[11px] text-gray-500">{result.disclaimer}</p>
                </div>
            )}
        </Card>
    );
}
