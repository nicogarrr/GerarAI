import Link from 'next/link';
import type { ResearchValuation } from '@/lib/actions/research.actions';
import { termLabel } from '@/components/research/FundamentalModelPanels';
import { sourceDisplay } from '@/lib/research/source-display';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/** Solo presenta el bloqueo persistido. No sustituye datos ni ajusta márgenes. */
export default function BlockedValuation({ valuation, ticker, locale = 'es' }: { valuation: ResearchValuation; ticker: string; locale?: Locale }) {
    const t = createTranslator(locale);
    const term = (raw: string) => termLabel(raw, locale);
    const missing = valuation.missing_inputs ?? [];
    const negativeFcf = missing.includes('non_negative_fcf_margin');
    const periods = Object.entries(valuation.trace?.periods ?? {}).filter(([, period]) => period);
    const factIds = Object.entries(valuation.trace?.fact_ids ?? {}).filter(([, id]) => id != null);
    const source = valuation.trace?.input_source;
    const href = (view: string) => `/research/${encodeURIComponent(ticker)}?view=${view}`;
    return (
        <section className="space-y-3 rounded-lg border border-amber-900/70 bg-amber-950/20 p-4 text-sm text-amber-200" aria-label={t('research.blockedValuation.ariaLabel')}>
            <h2 className="font-semibold">{t('research.blockedValuation.title', { model: term(valuation.model_type) })}</h2>
            <p>{negativeFcf
                ? t('research.blockedValuation.negativeFcf')
                : t('research.blockedValuation.missingInputs', { inputs: missing.map((item) => term(item)).join(', ') || t('research.blockedValuation.missingUnspecified') })}</p>
            <p className="text-xs text-gray-300">{t('research.blockedValuation.inputSource', { source: source && source !== 'insufficient_data' ? sourceDisplay(source, locale) : t('research.blockedValuation.sourceUnspecified') })}
                {' '}{t('research.blockedValuation.periods', { periods: periods.length ? periods.map(([metric, period]) => `${term(metric)}: ${period}`).join(' · ') : t('research.blockedValuation.periodsNone') })}
                {factIds.length ? ` ${t('research.blockedValuation.facts', { facts: factIds.map(([metric, id]) => `${term(metric)} #${id}`).join(' · ') })}` : null}
            </p>
            <nav aria-label={t('research.blockedValuation.navAria')} className="flex flex-wrap gap-x-4 gap-y-1">
                <Link className="inline-flex min-h-11 items-center text-teal-300 hover:underline" href={href('financials')}>{t('research.blockedValuation.reviewData')}</Link>
                <Link className="inline-flex min-h-11 items-center text-teal-300 hover:underline" href={href('supuestos')}>{t('research.blockedValuation.reviewAssumptions')}</Link>
                <Link className="inline-flex min-h-11 items-center text-teal-300 hover:underline" href={href('model')}>{t('research.blockedValuation.viewModel')}</Link>
            </nav>
        </section>
    );
}
