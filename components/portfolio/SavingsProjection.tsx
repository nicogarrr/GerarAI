'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { getPlan, getSavingsProjection, type PlanRecord } from '@/lib/actions/plan.actions';
import PlanSetupDialog from '@/components/plan/PlanSetupDialog';
import { parseLocalizedNumber, parseLocalizedNumberDetailed } from '@/lib/i18n/parse-number';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import type { SavingsProjection as Projection } from '@/lib/plan/savings-projection';

const control = 'min-h-[44px] w-full rounded-lg border border-gray-600 bg-gray-950 px-3 py-2 text-gray-100';
// Divisas habituales; la del plan (SEK, DKK, NOK...) se añade si no está, como en PlanSetupDialog.
const CURRENCY_OPTIONS = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'];
const panel = 'rounded-xl border border-gray-800 bg-gray-900/40 p-4';

export default function SavingsProjection() {
    const ti = useT();
    const locale = useLocale();
    const f = useFormat();
    const [plan, setPlan] = useState<PlanRecord | null>(null);
    const [projection, setProjection] = useState<Projection | null>(null);
    const [monthly, setMonthly] = useState(() => ti('portfolio.savings.monthlyInitial'));
    const [currency, setCurrency] = useState('EUR');
    const [years, setYears] = useState(20);
    const [dividendYield, setDividendYield] = useState('3');
    const [inflation, setInflation] = useState('2');
    const [rate, setRate] = useState(.05);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [dirty, setDirty] = useState(false);
    const inputVersion = useRef(0);
    const [planVersion, setPlanVersion] = useState(0);

    useEffect(() => {
        let active = true;
        Promise.all([getPlan(), getSavingsProjection()]).then(([record, data]) => {
            if (!active) return;
            setPlan(record);
            setProjection(data);
            if (typeof data.monthly_contribution === 'number') setMonthly(f.formatNumberForInput(data.monthly_contribution));
            if (data.currency) setCurrency(data.currency);
            else if (data.plan_exists) setCurrency('');
            if (data.horizon_years) setYears(data.horizon_years);
        }).catch(() => { if (active) setError(ti('portfolio.savings.errReadPlan')); })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [planVersion]);

    async function simulate(event: React.FormEvent) {
        event.preventDefault();
        if (!currency) {
            setError(ti('portfolio.savings.errCurrency'));
            return;
        }
        if ([monthly, dividendYield, inflation].some((value) => {
            const parsed = parseLocalizedNumberDetailed(value, locale);
            return !parsed.ok && parsed.error === 'ambiguous';
        })) {
            setError(ti('portfolio.transactionForm.errAmbiguous'));
            return;
        }
        const amount = parseLocalizedNumber(monthly, locale);
        const yieldPct = parseLocalizedNumber(dividendYield, locale);
        const inflationPct = parseLocalizedNumber(inflation, locale);
        if (amount === null || amount < 0 || amount > 1_000_000 || yieldPct === null || yieldPct < 0 || yieldPct > 50 || inflationPct === null || inflationPct <= -99 || inflationPct > 100) {
            setError(ti('portfolio.savings.errRange'));
            return;
        }
        const submittedVersion = inputVersion.current;
        setLoading(true);
        setError(null);
        try {
            setProjection(await getSavingsProjection({ monthly: amount, years, currency, dividendYield: yieldPct / 100, inflation: inflationPct / 100 }));
            // Inputs remain editable while the request is in flight. A late
            // result belongs to the submitted fields, not subsequent edits.
            setDirty(inputVersion.current !== submittedVersion);
        } catch {
            setError(ti('portfolio.savings.errCalc'));
        } finally { setLoading(false); }
    }
    const selected = projection?.scenarios.find((item) => Math.abs(item.annual_total_return - rate) < 1e-8);
    const unit = projection?.currency;
    const money = (n: number) => f.formatMoney(n, unit ?? 'EUR');
    const edit = () => { inputVersion.current += 1; setDirty(true); };
    return (
        <section className="mb-6 grid min-w-0 gap-4" aria-labelledby="savings-title" aria-busy={loading}>
            <div><h2 id="savings-title" className="text-xl font-semibold text-gray-100">{ti('portfolio.savings.title')}</h2></div>
            <form onSubmit={simulate} className={`${panel} grid gap-4`}>
                <p className="text-sm text-teal-300">{plan ? ti('portfolio.savings.connectedPlan') : ti('portfolio.savings.exampleUnsaved')}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-sm">{ti('portfolio.savings.monthlyLabel')}<input className={control} inputMode="decimal" value={monthly} onChange={(e) => { setMonthly(e.target.value); edit(); }} /></label>
                    <label className="grid gap-1 text-sm">{ti('portfolio.savings.currencyLabel')}<select className={control} value={currency} onChange={(e) => { setCurrency(e.target.value); edit(); }}><option value="">{ti('portfolio.savings.currencyPlaceholder')}</option>{(currency && !CURRENCY_OPTIONS.includes(currency) ? [currency, ...CURRENCY_OPTIONS] : CURRENCY_OPTIONS).map((c) => <option key={c}>{c}</option>)}</select></label>
                </div>
                <fieldset><legend className="mb-2 text-sm">{ti('portfolio.savings.horizonLegend')}</legend><div className="grid grid-cols-4 gap-2">{Array.from(new Set([5, 10, 20, 30, years])).sort((a, b) => a - b).map((y) => <button key={y} type="button" disabled={loading} aria-pressed={years === y} className={`min-h-[44px] rounded-lg border px-2 text-sm ${years === y ? 'border-teal-500 bg-teal-950 text-teal-200' : 'border-gray-700'}`} onClick={() => { setYears(y); edit(); }}>{ti('portfolio.savings.yearsLabel', { n: y })}</button>)}</div></fieldset>
                <details><summary className="min-h-[44px] cursor-pointer py-2 text-sm text-teal-300">{ti('portfolio.savings.assumptionsSummary')}</summary><div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-sm">{ti('portfolio.savings.dividendLabel')}<input className={control} inputMode="decimal" value={dividendYield} onChange={(e) => { setDividendYield(e.target.value); edit(); }} /></label>
                    <label className="grid gap-1 text-sm">{ti('portfolio.savings.inflationLabel')}<input className={control} inputMode="decimal" value={inflation} onChange={(e) => { setInflation(e.target.value); edit(); }} /></label>
                </div></details>
                <p className="rounded-lg bg-gray-800/60 p-3 text-sm text-gray-300">{ti('portfolio.savings.assumptionsNote')}</p>
                <button disabled={loading} className="min-h-[44px] rounded-lg bg-teal-700 px-4 py-2 font-semibold text-white disabled:opacity-50">{loading ? ti('portfolio.savings.calculating') : ti('portfolio.savings.simulateCta')}</button>
            </form>
            {error ? <p role="alert" className="rounded-lg border border-amber-700 p-3 text-sm text-amber-200">{error}</p> : null}
            {dirty ? <p role="status" className="text-sm text-amber-200">{ti('portfolio.savings.dirtyNotice')}</p> : null}
            {projection?.status === 'currency_missing' ? <p role="status" className="text-sm text-amber-200">{ti('portfolio.savings.currencyMissing')}</p> : null}
            {selected && unit ? <div className={`${panel} grid gap-3`}>
                <h3 className="text-lg font-semibold">{ti('portfolio.savings.inYears', { years: selected.years })}</h3>
                <p className="text-3xl font-semibold text-teal-300">{money(selected.terminal_value)}</p>
                <p className="text-sm text-gray-400">{ti('portfolio.savings.hypothesisLine', { rate: f.formatNumber(rate * 100) })}</p>
                <dl className="grid gap-3 text-sm">{[[ti('portfolio.savings.rowContributed'), selected.contributed], [ti('portfolio.savings.rowSimulated'), selected.simulated_return], [ti('portfolio.savings.rowToday'), selected.terminal_value_today_money]].map(([label, value]) => <div key={String(label)} className="flex flex-wrap justify-between gap-x-4 gap-y-1"><dt>{label}</dt><dd className="font-semibold">{money(Number(value))}</dd></div>)}</dl>
                <h4 className="border-t border-gray-700 pt-3 font-semibold">{ti('portfolio.savings.dividendsTitle')}</h4>
                <p>{ti('portfolio.savings.grossPerYear', { amount: money(selected.terminal_annual_gross_dividend) })}<br /><span className="text-sm text-gray-400">{ti('portfolio.savings.monthlyEquiv', { amount: money(selected.terminal_monthly_gross_dividend_equivalent) })}</span></p>
                <p className="text-sm text-gray-400">{ti('portfolio.savings.dividendHypothesis', { yield: f.formatNumber(selected.terminal_dividend_yield * 100) })}</p>
                <fieldset><legend className="mb-2 text-sm">{ti('portfolio.savings.compareLegend')}</legend><div className="grid gap-2">{projection.scenarios.map((item) => <button type="button" key={item.annual_total_return} onClick={() => setRate(item.annual_total_return)} aria-pressed={Math.abs(rate - item.annual_total_return) < 1e-8} className={`flex min-h-[44px] flex-wrap justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${rate === item.annual_total_return ? 'border-teal-500 text-teal-200' : 'border-gray-700'}`}><span>{ti('portfolio.savings.scenarioLabel', { rate: f.formatNumber(item.annual_total_return * 100) })}</span><b>{money(item.terminal_value)}</b></button>)}</div></fieldset>
                <p className="text-sm text-gray-400">{ti('portfolio.savings.disclaimer')}</p>
            </div> : null}
            <div className={`${panel} grid gap-3 text-sm`}>
                <h3 className="font-semibold">{ti('portfolio.savings.planPanelTitle')}</h3>
                <PlanSetupDialog triggerLabel={plan ? ti('portfolio.savings.editPlan') : ti('portfolio.savings.setupPlan')} initial={plan} onSaved={() => { setLoading(true); setDirty(false); setPlanVersion((v) => v + 1); }} />
                <Link className="inline-flex min-h-[44px] items-center text-teal-300" href="/plan">{ti('portfolio.savings.dcaSplitLink')}</Link>
            </div>
        </section>
    );
}
