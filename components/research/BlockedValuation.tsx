import Link from 'next/link';
import type { ResearchValuation } from '@/lib/actions/research.actions';
import { termLabel } from '@/components/research/FundamentalModelPanels';
import { sourceDisplay } from '@/lib/research/source-display';

/** Solo presenta el bloqueo persistido. No sustituye datos ni ajusta márgenes. */
export default function BlockedValuation({ valuation, ticker }: { valuation: ResearchValuation; ticker: string }) {
    const missing = valuation.missing_inputs ?? [];
    const negativeFcf = missing.includes('non_negative_fcf_margin');
    const periods = Object.entries(valuation.trace?.periods ?? {}).filter(([, period]) => period);
    const factIds = Object.entries(valuation.trace?.fact_ids ?? {}).filter(([, id]) => id != null);
    const source = valuation.trace?.input_source;
    const href = (view: string) => `/research/${encodeURIComponent(ticker)}?view=${view}`;
    return (
        <section className="space-y-3 rounded-lg border border-amber-900/70 bg-amber-950/20 p-4 text-sm text-amber-200" aria-label="Valoración bloqueada">
            <h2 className="font-semibold">Valoración bloqueada: {termLabel(valuation.model_type)}</h2>
            <p>{negativeFcf
                ? 'El margen de flujo de caja libre registrado es negativo. Este modelo DCF no puede valorarlo sin falsear el consumo de caja. Revisa un modelo de financiación y dilución; no fuerces un margen positivo.'
                : `Este modelo no puede publicar una valoración con las entradas disponibles: ${missing.map(termLabel).join(', ') || 'el motor no especifica las entradas que faltan'}.`}</p>
            <p className="text-xs text-gray-300">Fuente de las entradas: {source && source !== 'insufficient_data' ? sourceDisplay(source) : 'no especificada en esta valoración'}.
                {' '}Periodos: {periods.length ? periods.map(([metric, period]) => `${termLabel(metric)}: ${period}`).join(' · ') : 'no registrados'}.
                {factIds.length ? ` Hechos registrados: ${factIds.map(([metric, id]) => `${termLabel(metric)} #${id}`).join(' · ')}.` : null}
            </p>
            <nav aria-label="Revisar valoración bloqueada" className="flex flex-wrap gap-x-4 gap-y-1">
                <Link className="inline-flex min-h-11 items-center text-teal-300 hover:underline" href={href('financials')}>Revisar datos y fuentes</Link>
                <Link className="inline-flex min-h-11 items-center text-teal-300 hover:underline" href={href('supuestos')}>Revisar supuestos</Link>
                <Link className="inline-flex min-h-11 items-center text-teal-300 hover:underline" href={href('model')}>Ver modelo a largo plazo</Link>
            </nav>
        </section>
    );
}
