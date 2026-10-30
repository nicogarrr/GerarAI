'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { getPlan, getSavingsProjection, type PlanRecord } from '@/lib/actions/plan.actions';
import PlanSetupDialog from '@/components/plan/PlanSetupDialog';
import { formatMoney, formatNumber, formatNumberForInput, parseLocalizedNumber, parseLocalizedNumberDetailed } from '@/lib/format';
import type { SavingsProjection as Projection } from '@/lib/plan/savings-projection';

const control = 'min-h-[44px] w-full rounded-lg border border-gray-600 bg-gray-950 px-3 py-2 text-gray-100';
// Divisas habituales; la del plan (SEK, DKK, NOK...) se añade si no está, como en PlanSetupDialog.
const CURRENCY_OPTIONS = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'];
const panel = 'rounded-xl border border-gray-800 bg-gray-900/40 p-4';

export default function SavingsProjection() {
    const [plan, setPlan] = useState<PlanRecord | null>(null);
    const [projection, setProjection] = useState<Projection | null>(null);
    const [monthly, setMonthly] = useState('1.000');
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
            if (typeof data.monthly_contribution === 'number') setMonthly(formatNumberForInput(data.monthly_contribution));
            if (data.currency) setCurrency(data.currency);
            else if (data.plan_exists) setCurrency('');
            if (data.horizon_years) setYears(data.horizon_years);
        }).catch(() => { if (active) setError('No se pudo leer el plan. Puedes reintentar una proyección sin guardar.'); })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [planVersion]);

    async function simulate(event: React.FormEvent) {
        event.preventDefault();
        if (!currency) {
            setError('Elige la divisa de la aportación mensual.');
            return;
        }
        if ([monthly, dividendYield, inflation].some((value) => {
            const parsed = parseLocalizedNumberDetailed(value);
            return !parsed.ok && parsed.error === 'ambiguous';
        })) {
            setError('Formato de número ambiguo: usa la coma para los decimales y el punto para los miles (ej. 1.234,56).');
            return;
        }
        const amount = parseLocalizedNumber(monthly);
        const yieldPct = parseLocalizedNumber(dividendYield);
        const inflationPct = parseLocalizedNumber(inflation);
        if (amount === null || amount < 0 || amount > 1_000_000 || yieldPct === null || yieldPct < 0 || yieldPct > 50 || inflationPct === null || inflationPct <= -99 || inflationPct > 100) {
            setError('Revisa importe, dividendo (0–50 %) e inflación (mayor que −99 % y hasta 100 %).');
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
            setError('No se pudo calcular la proyección. Conservamos el resultado anterior, si lo hay.');
        } finally { setLoading(false); }
    }
    const selected = projection?.scenarios.find((item) => Math.abs(item.annual_total_return - rate) < 1e-8);
    const unit = projection?.currency;
    const money = (n: number) => formatMoney(n, unit ?? 'EUR');
    const edit = () => { inputVersion.current += 1; setDirty(true); };
    return (
        <section className="mb-6 grid min-w-0 gap-4" aria-labelledby="savings-title" aria-busy={loading}>
            <div><h2 id="savings-title" className="text-xl font-semibold text-gray-100">Tu ahorro a largo plazo</h2></div>
            <form onSubmit={simulate} className={`${panel} grid gap-4`}>
                <p className="text-sm text-teal-300">{plan ? 'Conectado a tu plan de inversión' : 'Ejemplo editable · no guardado'}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-sm">Aportación mensual<input className={control} inputMode="decimal" value={monthly} onChange={(e) => { setMonthly(e.target.value); edit(); }} /></label>
                    <label className="grid gap-1 text-sm">Divisa de la aportación<select className={control} value={currency} onChange={(e) => { setCurrency(e.target.value); edit(); }}><option value="">Elige divisa</option>{(currency && !CURRENCY_OPTIONS.includes(currency) ? [currency, ...CURRENCY_OPTIONS] : CURRENCY_OPTIONS).map((c) => <option key={c}>{c}</option>)}</select></label>
                </div>
                <fieldset><legend className="mb-2 text-sm">Horizonte</legend><div className="grid grid-cols-4 gap-2">{Array.from(new Set([5, 10, 20, 30, years])).sort((a, b) => a - b).map((y) => <button key={y} type="button" disabled={loading} aria-pressed={years === y} className={`min-h-[44px] rounded-lg border px-2 text-sm ${years === y ? 'border-teal-500 bg-teal-950 text-teal-200' : 'border-gray-700'}`} onClick={() => { setYears(y); edit(); }}>{y} años</button>)}</div></fieldset>
                <details><summary className="min-h-[44px] cursor-pointer py-2 text-sm text-teal-300">Supuestos de dividendos e inflación</summary><div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-sm">Dividendo final bruto (%)<input className={control} inputMode="decimal" value={dividendYield} onChange={(e) => { setDividendYield(e.target.value); edit(); }} /></label>
                    <label className="grid gap-1 text-sm">Inflación anual (%)<input className={control} inputMode="decimal" value={inflation} onChange={(e) => { setInflation(e.target.value); edit(); }} /></label>
                </div></details>
                <p className="rounded-lg bg-gray-800/60 p-3 text-sm text-gray-300">Capital inicial 0. Solo aportaciones al final de cada mes; tu cartera real no está incluida. Dividendo reinvertido dentro del retorno total, sin contarlo dos veces.</p>
                <button disabled={loading} className="min-h-[44px] rounded-lg bg-teal-700 px-4 py-2 font-semibold text-white disabled:opacity-50">{loading ? 'Calculando…' : 'Simular sin guardar'}</button>
            </form>
            {error ? <p role="alert" className="rounded-lg border border-amber-700 p-3 text-sm text-amber-200">{error}</p> : null}
            {dirty ? <p role="status" className="text-sm text-amber-200">Has cambiado los campos. Pulsa Simular para actualizar los resultados.</p> : null}
            {projection?.status === 'currency_missing' ? <p role="status" className="text-sm text-amber-200">Tu plan no tiene divisa registrada. Elige la divisa explícitamente para una proyección; no asumimos euros.</p> : null}
            {selected && unit ? <div className={`${panel} grid gap-3`}>
                <h3 className="text-lg font-semibold">Dentro de {selected.years} años</h3>
                <p className="text-3xl font-semibold text-teal-300">{money(selected.terminal_value)}</p>
                <p className="text-sm text-gray-400">Hipótesis {formatNumber(rate * 100)} % anual total, antes de impuestos e inflación.</p>
                <dl className="grid gap-3 text-sm">{[['Dinero aportado', selected.contributed], ['Rendimiento simulado', selected.simulated_return], ['Valor en dinero de hoy', selected.terminal_value_today_money]].map(([label, value]) => <div key={String(label)} className="flex flex-wrap justify-between gap-x-4 gap-y-1"><dt>{label}</dt><dd className="font-semibold">{money(Number(value))}</dd></div>)}</dl>
                <h4 className="border-t border-gray-700 pt-3 font-semibold">Dividendos al final del periodo</h4>
                <p>{money(selected.terminal_annual_gross_dividend)} brutos/año<br /><span className="text-sm text-gray-400">≈ {money(selected.terminal_monthly_gross_dividend_equivalent)}/mes equivalente, no calendario de cobros.</span></p>
                <p className="text-sm text-gray-400">Hipótesis de dividendo final: {formatNumber(selected.terminal_dividend_yield * 100)} %. Neto N/D: faltan fiscalidad y costes. No es una promesa de pagos.</p>
                <fieldset><legend className="mb-2 text-sm">Compara rentabilidad total supuesta</legend><div className="grid gap-2">{projection.scenarios.map((item) => <button type="button" key={item.annual_total_return} onClick={() => setRate(item.annual_total_return)} aria-pressed={Math.abs(rate - item.annual_total_return) < 1e-8} className={`flex min-h-[44px] flex-wrap justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${rate === item.annual_total_return ? 'border-teal-500 text-teal-200' : 'border-gray-700'}`}><span>{formatNumber(item.annual_total_return * 100)} % total anual</span><b>{money(item.terminal_value)}</b></button>)}</div></fieldset>
                <p className="text-sm text-gray-400">Son hipótesis, no probabilidades. Puedes perder capital. Los niveles DCA no mejoran automáticamente la rentabilidad supuesta.</p>
            </div> : null}
            <div className={`${panel} grid gap-3 text-sm`}>
                <h3 className="font-semibold">El mismo plan para Cartera, Cerebro y DCA</h3>
                <PlanSetupDialog triggerLabel={plan ? 'Editar mi plan' : 'Configurar mi plan'} initial={plan} onSaved={() => { setLoading(true); setDirty(false); setPlanVersion((v) => v + 1); }} />
                <Link className="inline-flex min-h-[44px] items-center text-teal-300" href="/plan">Ver reparto de la aportación por nivel DCA →</Link>
            </div>
        </section>
    );
}
