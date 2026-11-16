import { writeFileSync, mkdirSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { it } from 'vitest';
import { DeepValueResultSections } from '@/components/proPicks/DeepValueView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { DeepValueItem } from '@/lib/actions/propicks-deep-value.actions';

it('exports actual result cards in both locales for offline visual QA', () => {
    const base = { sector: 'Industrials', exchange: 'NASDAQ', price_to_book: 0.7, dividend_yield: 0.12,
        pb_price_date: '2026-11-13', pb_fiscal_year: 2025, metric_as_of: '2026-11-15',
        yield_status: 'ok', yield_extremo_revisar: false, desacuerdo_fuentes: false,
        finnhub_yield_indicated: null, fuentes: [], currency: 'USD' };
    const good: DeepValueItem = { ...base, ticker: 'EJEMPLO', name: 'Fixture, no recomendación', score: 58 };
    const para: DeepValueItem = { ...base, ticker: 'PARA', name: 'Banzai International Inc', dividend_yield: 96.15384615,
        price_to_book: 0.00024422, score: null, desacuerdo_fuentes: true, yield_extremo_revisar: true,
        finnhub_yield_indicated: 0.0140746, review_reasons: ['yield_sources_disagree', 'yield_extreme', 'pb_split_basis_unverified'] };
    const elme: DeepValueItem = { ...para, ticker: 'ELME', name: 'Elme Communities', dividend_yield: 34.8,
        price_to_book: 0.00406361, pb_fiscal_year: 2024, pb_price_date: '2026-11-05', sector: 'Real Estate', exchange: 'NYSE', finnhub_yield_indicated: 0.0550459, review_reasons: ['yield_sources_disagree', 'yield_extreme', 'pb_price_stale_or_invalid'] };
    mkdirSync('/tmp/dv-visuals', { recursive: true });
    for (const locale of ['es','en'] as const) writeFileSync(`/tmp/dv-visuals/${locale}.html`, renderToStaticMarkup(
        <LocaleProvider locale={locale}><main className="mx-auto max-w-6xl p-4"><h1 className="mb-4 text-xl text-gray-100">Deep value · fixture QA</h1>
            <DeepValueResultSections data={{ estrategia: 'deep-value-v1', rotulo: '', resultados: [good], pendientes_revision: [elme,para] }} />
        </main></LocaleProvider>));
});
