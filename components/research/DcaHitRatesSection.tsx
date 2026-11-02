import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaHitRatesState } from '@/lib/actions/dca-signals.actions';
import { getLocale, getT } from '@/lib/i18n/server';

const EMPTY_CLASS = 'rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-400';

/** Ficha de research: histórico de señales DCA si el ticker está en watchlist o cartera.
    El acordeón nunca queda vacío: cada estado dice lo que se sabe y nada más. */
export async function DcaHitRatesSection({ ticker }: { ticker: string }) {
    const [state, t, locale] = await Promise.all([getDcaHitRatesState(ticker), getT(), getLocale()]);
    if (state.status === 'not_evaluated') {
        return (
            <p role="status" data-testid="dca-hit-rates-not-evaluated" className={EMPTY_CLASS}>
                {t('watchlist.hitRates.section.notEvaluated')}
            </p>
        );
    }
    if (state.status === 'preparing') {
        return (
            <p role="status" aria-live="polite" data-testid="dca-hit-rates-preparing" className={EMPTY_CLASS}>
                {t('watchlist.hitRates.section.preparing')}
                <DcaPreparingRefresh />
            </p>
        );
    }
    if (state.status === 'unavailable') {
        return (
            <p role="status" data-testid="dca-hit-rates-unavailable" className={EMPTY_CLASS}>
                {t('watchlist.hitRates.section.unavailable')}
            </p>
        );
    }
    return (
        <section aria-label={t('watchlist.hitRates.section.label')} className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <DcaHitRatesCard data={state.data} ti={t} locale={locale} />
        </section>
    );
}
