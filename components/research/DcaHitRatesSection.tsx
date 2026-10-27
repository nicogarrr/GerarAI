import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaHitRatesState } from '@/lib/actions/dca-signals.actions';

const EMPTY_CLASS = 'rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-400';

/** Ficha de research: histórico de señales DCA si el ticker está en watchlist o cartera.
    El acordeón nunca queda vacío: cada estado dice lo que se sabe y nada más. */
export async function DcaHitRatesSection({ ticker }: { ticker: string }) {
    const state = await getDcaHitRatesState(ticker);
    if (state.status === 'not_evaluated') {
        return (
            <p role="status" data-testid="dca-hit-rates-not-evaluated" className={EMPTY_CLASS}>
                Este ticker aún no tiene señal DCA evaluada. El histórico aparece cuando está en tu watchlist o cartera y se ha evaluado.
            </p>
        );
    }
    if (state.status === 'unavailable') {
        return (
            <p role="status" data-testid="dca-hit-rates-unavailable" className={EMPTY_CLASS}>
                Histórico no disponible ahora mismo: no se pudo consultar el servicio. Vuelve a intentarlo más tarde.
            </p>
        );
    }
    return (
        <section aria-label="Histórico de señales DCA" className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <DcaHitRatesCard data={state.data} />
        </section>
    );
}
